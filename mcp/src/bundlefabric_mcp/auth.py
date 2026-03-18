"""BundleFabric MCP — JWT Auth Manager with auto-refresh."""
from __future__ import annotations
import time
import httpx


class AuthManager:
    """Manages BundleFabric JWT token lifecycle.

    Flow:
      1. POST /auth/token with API key → receive 24h JWT
      2. Before expiry (5min buffer) → auto-refresh
      3. All requests use Bearer <token>
    """

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._token: str = ""
        self._expires_at: float = 0.0

    async def init(self) -> None:
        """Fetch initial token at startup."""
        await self._refresh()

    async def get_token(self) -> str:
        """Return a valid JWT, refreshing if needed."""
        if time.time() > self._expires_at - 300:
            await self._refresh()
        return self._token

    async def auth_headers(self) -> dict[str, str]:
        """Return Authorization headers dict."""
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def _refresh(self) -> None:
        """POST /auth/token and store the new JWT."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{self._base_url}/auth/token",
                json={"api_key": self._api_key},
            )
            r.raise_for_status()
            data = r.json()
            self._token = data["token"]
            # BundleFabric tokens are valid 24h; track expiry client-side
            self._expires_at = time.time() + data.get("expires_in", 86400)
