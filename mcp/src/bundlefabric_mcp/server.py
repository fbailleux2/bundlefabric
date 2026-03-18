"""BundleFabric MCP Server — Phase 3 (tools + resources + prompts + dynamic bundles).

Static tools (7):
  - list_bundles         : discover available AI bundles
  - get_bundle           : full manifest for a specific bundle
  - execute_bundle       : run a bundle against an intent (calls DeerFlow)
  - system_status        : aggregated health: API + DeerFlow + Ollama
  - resolve_intent       : find best bundle(s) for a natural-language intent
  - get_history          : execution history (optional bundle filter)
  - get_execution        : detail of a single execution by id

Dynamic tools (1 per bundle, registered at startup via lifespan):
  - {bundle_id_snake}    : e.g. bundle_linux_ops, bundle_gtm_debug

Resources (4):
  - bundlefabric://bundles              : all bundles index (JSON)
  - bundlefabric://bundles/{bundle_id}  : bundle manifest (JSON)
  - bundlefabric://bundles/{bundle_id}/prompt : system prompt (Markdown)
  - bundlefabric://history/{exec_id}    : single execution (JSON)

Prompts (3):
  - use_bundle           : "use this bundle for this task"
  - explore_capabilities : "which bundle fits this need?"
  - debug_execution      : "analyse this execution output"
"""
from __future__ import annotations
import sys
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastmcp import FastMCP

from .config import settings
from .auth import AuthManager
from .client import BundleFabricClient

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    stream=sys.stderr,
)
log = logging.getLogger("bundlefabric_mcp")

# ── Lazy singletons — shared across all tool/resource/prompt handlers ─────────

_auth: Optional[AuthManager] = None
_client: Optional[BundleFabricClient] = None


async def _get_client() -> BundleFabricClient:
    global _auth, _client
    if _client is None:
        if not settings.api_key:
            raise RuntimeError(
                "BF_API_KEY is not set.\n"
                "Export it before starting the MCP server:\n"
                "  export BF_API_KEY=bf_<user>_<hex>"
            )
        _auth = AuthManager(settings.api_key, settings.api_url)
        await _auth.init()
        _client = BundleFabricClient(
            _auth, settings.api_url, execute_timeout=settings.execute_timeout
        )
        log.info("BundleFabric client initialised → %s", settings.api_url)
    return _client


# ── Dynamic bundle tool registration ─────────────────────────────────────────

def _register_bundle_tool(server: FastMCP, bundle: Dict[str, Any]) -> None:
    """Register one MCP tool for a specific bundle (called during lifespan)."""
    bid = bundle["id"]
    tool_name = bid.replace("-", "_")
    caps = ", ".join(bundle.get("capabilities", [])[:5])
    description = (
        f"{bundle['name']} — {bundle.get('description', 'Specialized AI bundle')}. "
        f"Capabilities: {caps}"
    )

    # Closure: capture bundle_id by value via make_fn pattern (avoids loop bug)
    def make_fn(bundle_id: str, desc: str):
        async def run_bundle(intent_text: str) -> Dict[str, Any]:
            """Execute this specialized AI bundle against a natural-language intent."""
            client = await _get_client()
            return await client.execute_bundle(bundle_id, intent_text)
        run_bundle.__doc__ = desc
        return run_bundle

    server.tool(make_fn(bid, description), name=tool_name, description=description)
    log.debug("Registered dynamic tool: %s", tool_name)


# ── Lifespan — startup / shutdown ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Pre-initialize client and register per-bundle dynamic tools at startup."""
    log.info("BundleFabric MCP server starting up…")
    try:
        client = await _get_client()
        bundles = await client.list_bundles()
        registered = 0
        for bundle in bundles[: settings.max_bundles]:
            try:
                _register_bundle_tool(server, bundle)
                registered += 1
            except Exception as exc:
                log.warning("Failed to register tool for %s: %s", bundle.get("id"), exc)
        log.info(
            "Dynamic bundle tools registered: %d / %d bundles",
            registered, len(bundles),
        )
    except Exception as exc:
        log.warning(
            "Dynamic bundle tool registration skipped (API unavailable?): %s", exc
        )

    yield  # Server runs here

    # Teardown
    global _auth, _client
    _auth = None
    _client = None
    log.info("BundleFabric MCP server shut down.")


# ── MCP instance ──────────────────────────────────────────────────────────────

mcp = FastMCP("BundleFabric", lifespan=lifespan)

# ── Static Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
async def list_bundles() -> Dict[str, Any]:
    """List all available BundleFabric bundles with their capabilities and TPS scores.

    Returns a summary of every active bundle: id, name, description,
    capabilities, TPS score, and usage count. Use this tool first to discover
    which bundle is appropriate for a given task.
    """
    client = await _get_client()
    bundles = await client.list_bundles()
    return {"count": len(bundles), "bundles": bundles}


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
async def resolve_intent(
    intent_text: str,
    top_k: int = 3,
) -> Dict[str, Any]:
    """Find the best BundleFabric bundle(s) for a natural-language intent.

    Uses keyword extraction + Qdrant RAG to rank bundles by relevance.
    Returns the top_k matches with relevance scores and explanations.

    Args:
        intent_text: Natural-language description of what you need.
        top_k:       Number of bundle matches to return (default: 3).
    """
    client = await _get_client()
    intent = await client.extract_intent(intent_text)
    matches = await client.resolve_intent(intent, top_k=top_k)
    return {
        "intent_goal": intent.get("goal"),
        "intent_keywords": intent.get("keywords", []),
        "matches": matches.get("matches", []),
    }


@mcp.tool()
async def execute_bundle(
    bundle_id: str,
    intent_text: str,
    workflow_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a BundleFabric bundle against a natural-language intent.

    Calls the DeerFlow LangGraph workflow with the bundle's system prompt
    and the extracted intent. May take 30-120s on CPU-only infra.

    Args:
        bundle_id:   Bundle to execute (e.g. 'bundle-linux-ops').
        intent_text: Natural-language description of what you want to achieve.
        workflow_id: Optional DeerFlow workflow override.

    Returns the execution result: status, output, and duration_ms.
    """
    client = await _get_client()
    return await client.execute_bundle(bundle_id, intent_text, workflow_id)


@mcp.tool()
async def get_history(
    bundle_id: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Get recent BundleFabric execution history.

    Args:
        bundle_id: Optional — filter to a specific bundle.
        limit:     Max number of records to return (default: 20, max: 200).

    Returns a list of past executions with status, intent, and output preview.
    """
    client = await _get_client()
    return await client.get_history(bundle_id=bundle_id, limit=min(limit, 200))


@mcp.tool()
async def get_execution(execution_id: int) -> Dict[str, Any]:
    """Get the full detail of a single BundleFabric execution.

    Args:
        execution_id: Integer id from the execution history.

    Returns the full execution record including complete output and goal.
    Raises an error if the execution_id does not exist.
    """
    client = await _get_client()
    try:
        result = await client.get_history_entry(execution_id)
    except Exception as exc:
        return {"error": str(exc), "execution_id": execution_id}
    if result is None:
        return {"error": f"Execution {execution_id} not found", "execution_id": execution_id}
    return result


@mcp.tool()
async def system_status() -> Dict[str, Any]:
    """Get the overall BundleFabric system status.

    Aggregates three health endpoints concurrently:
      - /health   : API liveness + version + uptime
      - /status   : bundle count, RAG indexing, system info
      - /deerflow/status : LangGraph + Ollama availability

    Use this to diagnose issues before executing bundles.
    """
    client = await _get_client()
    results: Dict[str, Any] = {}
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


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource("bundlefabric://bundles", description="Index of all available BundleFabric bundles")
async def resource_all_bundles() -> str:
    """Return JSON array of all bundles with capabilities and TPS scores."""
    client = await _get_client()
    bundles = await client.list_bundles()
    return json.dumps({"count": len(bundles), "bundles": bundles}, indent=2)


@mcp.resource(
    "bundlefabric://bundles/{bundle_id}",
    description="Full manifest for a specific bundle",
)
async def resource_bundle_manifest(bundle_id: str) -> str:
    """Return the complete JSON manifest for a bundle."""
    client = await _get_client()
    manifest = await client.get_bundle(bundle_id)
    return json.dumps(manifest, indent=2)


@mcp.resource(
    "bundlefabric://bundles/{bundle_id}/prompt",
    description="System prompt injected into DeerFlow for a bundle",
)
async def resource_bundle_prompt(bundle_id: str) -> str:
    """Return the system prompt (Markdown) that BundleFabric injects into DeerFlow."""
    client = await _get_client()
    dr = await client.dry_run(bundle_id, "What is your purpose and what can you do?")
    return dr.get("system_prompt", f"# Bundle: {bundle_id}\n\nNo system prompt available.")


@mcp.resource(
    "bundlefabric://history/{exec_id}",
    description="Full result of a past BundleFabric execution",
)
async def resource_execution_history(exec_id: str) -> str:
    """Return the complete execution record including output and metadata."""
    client = await _get_client()
    try:
        result = await client.get_history_entry(int(exec_id))
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc), "exec_id": exec_id})


# ── Prompts ───────────────────────────────────────────────────────────────────

@mcp.prompt(name="use_bundle", description="Template to invoke a specific bundle for a task")
async def prompt_use_bundle(bundle_id: str, task_description: str) -> str:
    """Generate a prompt that directs Claude to use a specific bundle."""
    try:
        client = await _get_client()
        caps_data = await client.get_capabilities(bundle_id)
        caps = ", ".join(caps_data.get("capabilities", [])[:6])
        bundle_name = caps_data.get("name", bundle_id)
    except Exception:
        caps = ""
        bundle_name = bundle_id

    lines = [
        f"Utilise le bundle **{bundle_name}** (`{bundle_id}`) pour accomplir la tâche suivante :",
        "",
        f"> {task_description}",
        "",
    ]
    if caps:
        lines += [f"Ce bundle est spécialisé en : {caps}", ""]
    lines += [
        "Appelle l'outil `execute_bundle` avec :",
        f'- `bundle_id`: "{bundle_id}"',
        f'- `intent_text`: [reformule la tâche en une phrase d\'intention claire]',
    ]
    return "\n".join(lines)


@mcp.prompt(
    name="explore_capabilities",
    description="Template to discover which bundle fits a user need",
)
async def prompt_explore_capabilities(user_need: str) -> str:
    """Generate a prompt that directs Claude to find the best bundle."""
    return "\n".join([
        "L'utilisateur a besoin d'aide avec :",
        "",
        f"> {user_need}",
        "",
        "Procède en deux étapes :",
        "1. Appelle `resolve_intent` avec ce besoin pour trouver les bundles les plus adaptés.",
        "2. Présente les 3 meilleurs résultats avec leur score de pertinence et explique",
        "   pourquoi chacun correspond (ou non) au besoin.",
        "",
        "Si aucun bundle ne correspond parfaitement, suggère une combinaison ou explique",
        "comment adapter le besoin.",
    ])


@mcp.prompt(
    name="debug_execution",
    description="Template to analyse a BundleFabric execution result",
)
async def prompt_debug_execution(
    bundle_id: str,
    intent_text: str,
    output: str,
    status: str,
) -> str:
    """Generate a prompt that directs Claude to analyse an execution result."""
    return "\n".join([
        "Voici le résultat d'une exécution BundleFabric :",
        "",
        f"- **Bundle** : `{bundle_id}`",
        f"- **Intent** : {intent_text}",
        f"- **Statut** : {status}",
        "",
        "**Output** :",
        "```",
        output[:2000] + ("…" if len(output) > 2000 else ""),
        "```",
        "",
        "Analyse ce résultat :",
        "1. L'output répond-il bien à l'intent initial ?",
        "2. Si le statut est `error`, quelle en est la cause probable ?",
        "3. Quelles améliorations suggères-tu (reformulation de l'intent, autre bundle, etc.) ?",
    ])


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server.

    Transport is controlled by FASTMCP_TRANSPORT env var (default: stdio).
    For SSE/HTTP mode: set FASTMCP_TRANSPORT=sse FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8090
    """
    log.info("Starting BundleFabric MCP server…")
    mcp.run()


if __name__ == "__main__":
    main()
