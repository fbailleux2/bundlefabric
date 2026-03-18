"""BundleFabric — JWT auth module. API key → JWT token. Protected routes via Depends."""
from __future__ import annotations
import os
import json
import time
import pathlib
from typing import Optional, Dict, Any

import jwt
import secrets
import hmac
import hashlib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Path to optional jwt_secret.txt override
_JWT_SECRET_FILE = pathlib.Path(os.getenv("USERS_FILE", "/app/secrets_vault/users.json")).parent / "jwt_secret.txt"


def _load_jwt_secret() -> str:
    """Load JWT secret: file takes priority over env var."""
    if _JWT_SECRET_FILE.exists():
        s = _JWT_SECRET_FILE.read_text().strip()
        if s:
            print(f"[Auth] JWT secret loaded from {_JWT_SECRET_FILE}")
            return s
    return os.getenv("JWT_SECRET", "change_me_in_production")


JWT_SECRET = _load_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 86400  # 24h
USERS_FILE = os.getenv("USERS_FILE", "/app/secrets_vault/users.json")

_bearer_scheme = HTTPBearer(auto_error=False)

# ── User store ───────────────────────────────────────────────────────────────

_users: Dict[str, Dict[str, Any]] = {}  # api_key → {username, role}


def _load_users() -> None:
    global _users
    try:
        p = pathlib.Path(USERS_FILE)
        if p.exists():
            data = json.loads(p.read_text())
            _users = {u["api_key"]: {"username": u["username"], "role": u.get("role", "user")}
                      for u in data if "api_key" in u and "username" in u}
            print(f"[Auth] Loaded {len(_users)} user(s) from {USERS_FILE}")
        else:
            print(f"[Auth] WARNING: users file not found at {USERS_FILE} — auth disabled")
    except Exception as e:
        print(f"[Auth] WARNING: failed to load users: {e}")


_load_users()


def reload_users() -> int:
    """Reload users from file into memory. Returns count."""
    _load_users()
    return len(_users)


def save_users(users_list: list) -> None:
    """Write users list to USERS_FILE."""
    p = pathlib.Path(USERS_FILE)
    p.write_text(__import__('json').dumps(users_list, indent=2, ensure_ascii=False))


def list_users() -> list:
    """Return list of users with api_key masked."""
    p = pathlib.Path(USERS_FILE)
    if not p.exists():
        return []
    data = __import__('json').loads(p.read_text())
    result = []
    for u in data:
        masked = u['api_key'][:12] + '****' if len(u.get('api_key', '')) > 12 else '****'
        result.append({
            'username': u['username'],
            'role': u.get('role', 'user'),
            'api_key_masked': masked,
            'api_key': u['api_key'],
        })
    return result


def create_user(username: str, role: str = 'user') -> Dict[str, Any]:
    """Create a new user with generated API key. Returns user dict with clear api_key."""
    p = pathlib.Path(USERS_FILE)
    data = __import__('json').loads(p.read_text()) if p.exists() else []
    if any(u['username'] == username for u in data):
        raise ValueError(f"User '{username}' already exists")
    api_key = f"bf_{username[:8]}_{secrets.token_hex(24)}"
    data.append({'username': username, 'api_key': api_key, 'role': role})
    save_users(data)
    reload_users()
    return {'username': username, 'api_key': api_key, 'role': role}


def delete_user(username: str) -> bool:
    """Delete a user by username. Returns True if deleted."""
    p = pathlib.Path(USERS_FILE)
    if not p.exists():
        return False
    data = __import__('json').loads(p.read_text())
    new_data = [u for u in data if u['username'] != username]
    if len(new_data) == len(data):
        return False
    save_users(new_data)
    reload_users()
    return True




def rotate_jwt_secret() -> str:
    """Generate new JWT secret, persist to file, update in-memory. Returns new secret."""
    global JWT_SECRET
    new_secret = secrets.token_hex(32)
    _JWT_SECRET_FILE.write_text(new_secret)
    JWT_SECRET = new_secret
    print(f"[Auth] JWT secret rotated — all existing tokens invalidated")
    return new_secret


def generate_oauth_state() -> str:
    """Generate HMAC-signed OAuth state (stateless, no DB needed)."""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    raw = f"{ts}:{nonce}"
    sig = hmac.new(JWT_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{raw}:{sig}"


def verify_oauth_state(state: str, max_age: int = 600) -> bool:
    """Verify HMAC-signed OAuth state. Returns True if valid and not expired."""
    try:
        last_colon = state.rfind(':')
        if last_colon == -1:
            return False
        raw, sig = state[:last_colon], state[last_colon + 1:]
        expected = hmac.new(JWT_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return False
        ts = int(raw.split(':')[0])
        return abs(time.time() - ts) < max_age
    except Exception:
        return False


def find_user_by_github(github_login: str) -> Optional[Dict[str, Any]]:
    """Find BF user by github_username field, then by username match."""
    p = pathlib.Path(USERS_FILE)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    # Priority: explicit github_username field
    for u in data:
        if u.get('github_username') == github_login:
            return u
    # Fallback: username matches github login
    for u in data:
        if u.get('username') == github_login:
            return u
    return None


def create_oauth_user(github_login: str) -> Dict[str, Any]:
    """Auto-provision a BF user from GitHub OAuth. Role=user by default."""
    p = pathlib.Path(USERS_FILE)
    data = json.loads(p.read_text()) if p.exists() else []
    api_key = f"bf_{github_login[:8]}_{secrets.token_hex(24)}"
    user = {
        'username': github_login,
        'api_key': api_key,
        'role': 'user',
        'github_username': github_login,
    }
    data.append(user)
    save_users(data)
    reload_users()
    print(f"[Auth] Auto-provisioned OAuth user: {github_login}")
    return user


def create_token_for_user(user: Dict[str, Any]) -> str:
    """Create JWT token directly from a user dict (used by OAuth callback)."""
    payload = {
        'sub': user['username'],
        'role': user.get('role', 'user'),
        'iat': int(time.time()),
        'exp': int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# ── Token operations ─────────────────────────────────────────────────────────

def create_token(api_key: str) -> Optional[Dict[str, Any]]:
    """Validate api_key and return JWT token payload. None if invalid."""
    user = _users.get(api_key)
    if not user:
        return None
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"token": token, "username": user["username"], "role": user["role"],
            "expires_in": JWT_EXPIRY_SECONDS}


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT. Returns payload or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """FastAPI Depends — raises 401 if not authenticated."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required — provide Bearer token via /auth/token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired — re-authenticate via /auth/token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """FastAPI Depends — raises 401/403 if not authenticated or not admin."""
    payload = await require_auth(credentials)
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return payload
