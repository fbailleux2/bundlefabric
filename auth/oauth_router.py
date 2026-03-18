"""BundleFabric — OAuth2 router (GitHub). Mount via app.include_router()."""
from __future__ import annotations

import json
import os
import pathlib

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse

from auth.jwt_auth import (
    create_oauth_user,
    create_token_for_user,
    find_user_by_github,
    generate_oauth_state,
    verify_oauth_state,
)

router = APIRouter(tags=["OAuth"])

# ── Config ────────────────────────────────────────────────────────────────────

def _load_github_config() -> tuple[str, str]:
    """Load GitHub OAuth client_id/secret from secrets_vault or env."""
    secrets_dir = pathlib.Path(
        os.getenv("USERS_FILE", "/app/secrets_vault/users.json")
    ).parent
    config_file = secrets_dir / "github_oauth.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text())
            return data.get("client_id", ""), data.get("client_secret", "")
        except Exception:
            pass
    return (
        os.getenv("GITHUB_CLIENT_ID", ""),
        os.getenv("GITHUB_CLIENT_SECRET", ""),
    )


WEBUI_URL = os.getenv("WEBUI_URL", "https://app.bundlefabric.org")
API_URL = os.getenv("API_URL", "https://api.bundlefabric.org")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/auth/oauth/providers")
async def oauth_providers():
    """Return which OAuth providers are configured."""
    client_id, _ = _load_github_config()
    return {"github": bool(client_id)}


@router.get("/auth/oauth/github")
async def oauth_github_start():
    """Redirect user to GitHub OAuth authorization page."""
    client_id, _ = _load_github_config()
    if not client_id:
        return JSONResponse(
            status_code=503,
            content={"detail": "GitHub OAuth not configured — set GITHUB_CLIENT_ID"},
        )
    state = generate_oauth_state()
    callback_uri = f"{API_URL}/auth/oauth/github/callback"
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={callback_uri}"
        f"&scope=read:user"
        f"&state={state}"
    )
    return RedirectResponse(url=github_url)


@router.get("/auth/oauth/github/callback")
async def oauth_github_callback(code: str = "", state: str = "", error: str = ""):
    """GitHub OAuth callback — exchange code for JWT, redirect to WebUI."""
    err_redirect = lambda msg: RedirectResponse(url=f"{WEBUI_URL}/#oauth_error={msg}")

    if error:
        return err_redirect(error)

    if not state or not verify_oauth_state(state):
        return err_redirect("invalid_state")

    if not code:
        return err_redirect("missing_code")

    client_id, client_secret = _load_github_config()
    if not client_id:
        return err_redirect("oauth_not_configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1 — Exchange code for access token
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return err_redirect("token_exchange_failed")

        token_data = resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            return err_redirect("no_access_token")

        # 2 — Get GitHub user info
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if user_resp.status_code != 200:
            return err_redirect("github_user_failed")

        github_user = user_resp.json()
        github_login = github_user.get("login", "")
        if not github_login:
            return err_redirect("no_github_login")

    # 3 — Find or create BundleFabric user
    bf_user = find_user_by_github(github_login)
    if not bf_user:
        bf_user = create_oauth_user(github_login)

    # 4 — Generate JWT and redirect to WebUI with fragment
    jwt_token = create_token_for_user(bf_user)
    username = bf_user.get("username", github_login)
    role = bf_user.get("role", "user")

    redirect_url = (
        f"{WEBUI_URL}/#oauth_token={jwt_token}"
        f"&oauth_user={username}"
        f"&oauth_role={role}"
    )
    return RedirectResponse(url=redirect_url)
