"""BundleFabric MCP — Async HTTP client wrapping the BundleFabric REST API."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import httpx
from .auth import AuthManager


class BundleFabricClient:
    """Thin async wrapper around BundleFabric REST API."""

    def __init__(self, auth: AuthManager, base_url: str) -> None:
        self._auth = auth
        self._base = base_url.rstrip("/")

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _get(self, path: str, **params) -> Any:
        headers = await self._auth.auth_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self._base}{path}", headers=headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, body: Dict[str, Any]) -> Any:
        headers = await self._auth.auth_headers()
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self._base}{path}", headers=headers, json=body)
            r.raise_for_status()
            return r.json()

    # ── Bundle endpoints ──────────────────────────────────────────────────────

    async def list_bundles(self) -> List[Dict[str, Any]]:
        """GET /bundles — return list of bundle summaries."""
        data = await self._get("/bundles")
        return data.get("bundles", data)

    async def get_bundle(self, bundle_id: str) -> Dict[str, Any]:
        """GET /bundles/{id} — return full bundle manifest."""
        return await self._get(f"/bundles/{bundle_id}")

    async def get_capabilities(self, bundle_id: str) -> Dict[str, Any]:
        """GET /bundles/{id}/capabilities — lightweight capabilities."""
        return await self._get(f"/bundles/{bundle_id}/capabilities")

    async def get_stats(self, bundle_id: str) -> Dict[str, Any]:
        """GET /bundles/{id}/stats — execution statistics."""
        return await self._get(f"/bundles/{bundle_id}/stats")

    # ── Execution endpoints ───────────────────────────────────────────────────

    async def execute_bundle(self, bundle_id: str, intent_text: str,
                             workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """POST /execute — run a bundle via DeerFlow."""
        body: Dict[str, Any] = {"bundle_id": bundle_id, "intent_text": intent_text}
        if workflow_id:
            body["workflow_id"] = workflow_id
        return await self._post("/execute", body)

    async def dry_run(self, bundle_id: str, intent_text: str) -> Dict[str, Any]:
        """POST /execute/dry-run — resolve intent without calling DeerFlow."""
        return await self._post("/execute/dry-run", {
            "bundle_id": bundle_id,
            "intent_text": intent_text,
        })

    # ── History endpoints ─────────────────────────────────────────────────────

    async def get_history(self, bundle_id: Optional[str] = None,
                          limit: int = 20) -> Dict[str, Any]:
        """GET /history — return recent executions."""
        params: Dict[str, Any] = {"limit": limit}
        if bundle_id:
            params["bundle_id"] = bundle_id
        return await self._get("/history", **params)

    async def search_history(self, q: str, limit: int = 20) -> Dict[str, Any]:
        """GET /history/search?q= — full-text search."""
        return await self._get("/history/search", q=q, limit=limit)

    # ── Status endpoints ──────────────────────────────────────────────────────

    async def health(self) -> Dict[str, Any]:
        """GET /health."""
        return await self._get("/health")

    async def status(self) -> Dict[str, Any]:
        """GET /status."""
        return await self._get("/status")

    async def deerflow_status(self) -> Dict[str, Any]:
        """GET /deerflow/status."""
        return await self._get("/deerflow/status")
