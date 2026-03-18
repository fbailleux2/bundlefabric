"""BundleFabric MCP Server — Phase 3 MVP.

4 core tools:
  - list_bundles     : discover available AI bundles
  - get_bundle       : full manifest for a specific bundle
  - execute_bundle   : run a bundle against an intent (calls DeerFlow)
  - system_status    : health + DeerFlow status aggregated
"""
from __future__ import annotations
import sys
import asyncio
import logging
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from .config import settings
from .auth import AuthManager
from .client import BundleFabricClient

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    stream=sys.stderr,
)
log = logging.getLogger("bundlefabric_mcp")

# ── MCP instance ──────────────────────────────────────────────────────────────

mcp = FastMCP(
    "BundleFabric",
    description=(
        "Cognitive OS — discover and execute AI bundles. "
        "Bundles are specialized AI programs (Linux ops, GTM debug, …) "
        "that map natural-language intent to structured DeerFlow workflows."
    ),
)

# ── Lazy singletons (initialised in lifespan) ─────────────────────────────────

_auth: Optional[AuthManager] = None
_client: Optional[BundleFabricClient] = None


async def _get_client() -> BundleFabricClient:
    global _auth, _client
    if _client is None:
        if not settings.api_key:
            raise RuntimeError(
                "BF_API_KEY is not set. "
                "Export it before starting the MCP server:\n"
                "  export BF_API_KEY=bf_<user>_<hex>"
            )
        _auth = AuthManager(settings.api_key, settings.api_url)
        await _auth.init()
        _client = BundleFabricClient(_auth, settings.api_url)
        log.info("BundleFabric client initialised → %s", settings.api_url)
    return _client


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_bundles() -> Dict[str, Any]:
    """List all available BundleFabric bundles with their capabilities and TPS scores.

    Returns a summary of every active bundle including id, name, description,
    capabilities, TPS score, and usage count. Use this tool first to discover
    which bundle is appropriate for a given task.
    """
    client = await _get_client()
    bundles = await client.list_bundles()
    return {
        "count": len(bundles),
        "bundles": bundles,
    }


@mcp.tool()
async def get_bundle(bundle_id: str) -> Dict[str, Any]:
    """Get the full manifest for a specific BundleFabric bundle.

    Args:
        bundle_id: The unique bundle identifier (e.g. 'bundle-linux-ops').

    Returns the complete bundle manifest including capabilities, domains,
    keywords, temporal score details, and workflow configuration.
    """
    client = await _get_client()
    return await client.get_bundle(bundle_id)


@mcp.tool()
async def execute_bundle(
    bundle_id: str,
    intent_text: str,
    workflow_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a BundleFabric bundle against a natural-language intent.

    This calls the DeerFlow LangGraph workflow with the bundle's system prompt
    and the extracted intent. Execution may take 30-120s on CPU-only infra.

    Args:
        bundle_id:   Bundle to execute (e.g. 'bundle-linux-ops').
        intent_text: Natural-language description of what you want to achieve.
        workflow_id: Optional DeerFlow workflow override.

    Returns the execution result including status, output, and duration.
    """
    client = await _get_client()
    return await client.execute_bundle(bundle_id, intent_text, workflow_id)


@mcp.tool()
async def system_status() -> Dict[str, Any]:
    """Get the overall BundleFabric system status.

    Aggregates:
      - API health (/health)
      - System info (/status): version, uptime, bundle count, RAG status
      - DeerFlow status (/deerflow/status): LangGraph + Ollama availability

    Use this to diagnose issues before executing bundles.
    """
    client = await _get_client()
    results: Dict[str, Any] = {}

    # Run all three status checks concurrently
    health_task = asyncio.create_task(client.health())
    status_task = asyncio.create_task(client.status())
    deerflow_task = asyncio.create_task(client.deerflow_status())

    for label, task in [
        ("health", health_task),
        ("status", status_task),
        ("deerflow", deerflow_task),
    ]:
        try:
            results[label] = await task
        except Exception as exc:
            results[label] = {"error": str(exc)}

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server (stdio transport by default)."""
    log.info("Starting BundleFabric MCP server (transport=%s)", settings.transport)
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    main()
