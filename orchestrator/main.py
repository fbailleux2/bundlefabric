"""BundleFabric Orchestrator — FastAPI main application.

Entry point for the BundleFabric Cognitive OS API:
  - Intent extraction (keyword → Ollama → Claude Haiku)
  - Bundle resolution (RAG + TPS scoring)
  - DeerFlow execution (LangGraph + Claude Haiku fallback)
  - History persistence (SQLite via aiosqlite)
  - Prometheus metrics, JWT auth, Phase 3 mesh/fusion/meta-agent routes
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

sys.path.insert(0, "/opt/bundlefabric")

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from models.bundle import BundleManifest
from models.intent import Intent, BundleMatch, ExecutionResult
from factory.loader import BundleLoader, BundleNotFoundError
from factory.builder import BundleBuilder
from factory.evaluator import BundleEvaluator
from orchestrator.intent_engine import IntentEngine, _claude_available, claude_execute_stream as _claude_execute_stream
from orchestrator.bundle_resolver import BundleResolver
from orchestrator.deerflow_client import DeerFlowClient
from memory.rag_manager import RAGManager
from memory.history_manager import init_db, record_execution, get_history, get_execution, search_history, get_bundle_stats
from auth.jwt_auth import require_auth, require_admin, create_token, list_users, create_user, delete_user, rotate_jwt_secret
from logging_config import get_logger, request_id_var

logger = get_logger("orchestrator.main")


# Prometheus metrics
from prometheus_client import Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from fastapi.responses import Response as _Response

VERSION = "2.1.0"
START_TIME = time.time()

# ── Singletons ──────────────────────────────────────────────────────────────
loader = BundleLoader()
builder = BundleBuilder()
bundles_dir = str(loader.bundles_dir)
evaluator = BundleEvaluator()
intent_engine = IntentEngine(use_ollama=os.getenv("USE_OLLAMA", "true").lower() == "true")
resolver = BundleResolver(loader=loader)
deerflow = DeerFlowClient()
rag = RAGManager()

_rag_indexed_count: int = 0
_rag_total_count: int = 0


async def _startup_index_bundles() -> None:
    """Index all bundles into Qdrant at startup. Non-blocking — runs as a background task."""
    global _rag_indexed_count, _rag_total_count
    await asyncio.sleep(2)  # Brief delay so Qdrant has time to start
    try:
        bundles = loader.list_bundles()
        _rag_total_count = len(bundles)
        if not bundles:
            logger.info("No bundles to index at startup")
            return
        rag.ensure_collection()
        indexed = 0
        for bundle in bundles:
            try:
                if rag.index_bundle(bundle):
                    indexed += 1
            except Exception as exc:
                logger.warning("Startup: failed to index bundle '%s': %s", bundle.id, exc)
        _rag_indexed_count = indexed
        logger.info("Startup RAG indexing complete — %d/%d bundles indexed", indexed, len(bundles))
    except Exception as exc:
        logger.warning("Startup RAG indexing error (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context: initialise DB + start background RAG indexing."""
    logger.info("BundleFabric API v%s starting...", VERSION)
    await init_db()
    task = asyncio.create_task(_startup_index_bundles())
    yield
    task.cancel()
    logger.info("BundleFabric API stopped.")


import auth.oauth_router as _oauth_router
# Phase 3 imports
from security.crypto_manager import BundleCryptoManager as _CryptoManager
from mesh.bundle_registry import BundleRegistry as _BundleRegistry
from mesh.friend_mesh import FriendMesh as _FriendMesh
from factory.fusion import BundleFusion as _BundleFusion
from factory.meta_agent import MetaAgent as _MetaAgent
from factory.evaluator import BundleEvaluator as _BundleEvaluator


app = FastAPI(
    title="BundleFabric API",
    description="Cognitive OS Orchestrator — intent → bundle → DeerFlow",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.bundlefabric.org",
        "https://bundlefabric.org",
        "https://www.bundlefabric.org",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Assign a short request-ID to every HTTP request.

    The ID is propagated via ContextVar so all log lines emitted during the
    request automatically include it, making cross-module tracing trivial.
    Set X-Request-ID header on the request to force a specific ID (e.g. from
    an upstream proxy or during tests).
    """
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    token = request_id_var.set(req_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        request_id_var.reset(token)


app.include_router(_oauth_router.router)


# Phase 3 singletons
_crypto = _CryptoManager()
_registry = _BundleRegistry()
_mesh = _FriendMesh()
_fusion = _BundleFusion()
_meta_agent = _MetaAgent()
_evaluator_p3 = _BundleEvaluator()


# Prometheus Gauges
_tps_gauge = Gauge('bundlefabric_bundle_tps', 'TPS score per bundle', ['bundle_id'])
_usage_gauge = Gauge('bundlefabric_bundle_usage_total', 'Usage count per bundle', ['bundle_id'])
_bundles_loaded = Gauge('bundlefabric_bundles_loaded', 'Number of bundles loaded')
_executions_counter = Counter('bundlefabric_executions_total', 'Total execution requests')
_intent_counter = Counter('bundlefabric_intent_requests_total', 'Total intent requests')




# ── Request/Response models ─────────────────────────────────────────────────

class IntentRequest(BaseModel):
    text: str
    use_ollama: bool = True
    use_claude: bool = False


class ResolveRequest(BaseModel):
    intent: Dict[str, Any]
    top_k: int = 5
    filter_archival: bool = True


class ExecuteRequest(BaseModel):
    bundle_id: str
    intent_text: str
    workflow_id: Optional[str] = None


class DryRunRequest(BaseModel):
    bundle_id: str
    intent_text: str


class CreateBundleRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    capabilities: List[str]
    domains: List[str] = []
    keywords: List[str] = []
    version: str = "1.0.0"
    author: str = "bundlefabric"
    freshness_score: float = 0.8


class UpdateBundleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    capabilities: Optional[List[str]] = None
    domains: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    version: Optional[str] = None


class TokenRequest(BaseModel):
    api_key: str


class CreateUserRequest(BaseModel):
    username: str
    role: str = "user"




@app.post("/admin/jwt/rotate", tags=["Admin"])
async def admin_rotate_jwt(_auth=Depends(require_admin)):
    """Rotate JWT signing secret. All existing tokens are immediately invalidated. Admin only."""
    new_secret = rotate_jwt_secret()
    return {
        "status": "rotated",
        "warning": "all tokens invalidated — all users must re-authenticate",
        "secret_preview": new_secret[:8] + "****",
    }




# ═══════════════════════════════════════════════════════════════
# PHASE 3 ROUTES
# ═══════════════════════════════════════════════════════════════

# ── Bundle crypto & public ────────────────────────────────────────────────────

@app.get("/bundles/public", tags=["Bundles"])
async def list_public_bundles():
    """List bundles marked public:true — no authentication required."""
    _registry.refresh_local()
    return {"bundles": _registry.get_public(), "count": len(_registry.get_public())}


@app.get("/bundles/{bundle_id}/hash", tags=["Bundles"])
async def get_bundle_hash(bundle_id: str, _auth=Depends(require_auth)):
    """Return SHA-256 hash + signed status of a bundle's manifest."""
    import pathlib
    bundle_path = pathlib.Path(bundles_dir) / bundle_id
    if not bundle_path.exists():
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")
    try:
        hash_val = _crypto.hash_bundle(bundle_path)
        signed = _crypto.is_bundle_signed(bundle_path)
        return {"bundle_id": bundle_id, "hash": hash_val, "signed": signed, "node_id": _crypto.get_node_id()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bundles/{bundle_id}/health", tags=["Bundles"])
async def get_bundle_health(bundle_id: str, _auth=Depends(require_auth)):
    """Return TPS, obsolescence score, age, and alerts for a bundle."""
    import pathlib
    bundle_path = pathlib.Path(bundles_dir) / bundle_id
    if not bundle_path.exists():
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")
    return _evaluator_p3.get_bundle_health(bundle_path)


# ── Mesh routes ───────────────────────────────────────────────────────────────

@app.get("/mesh/status", tags=["Mesh"])
async def mesh_status():
    """Return Friend Mesh status (enabled, node_id, peer_count, bundle_count)."""
    return _mesh.get_status()


@app.get("/mesh/peers", tags=["Mesh"])
async def mesh_peers():
    """Return online/offline status of all configured peers."""
    peers = await _mesh.get_peers_status()
    return {"peers": peers}


@app.get("/mesh/bundles", tags=["Mesh"])
async def mesh_advertise():
    """Advertise local bundles to mesh peers (manifest metadata only, no RAG)."""
    return _mesh.advertise_bundles()


@app.get("/mesh/bundles/{bundle_id}/manifest", tags=["Mesh"])
async def mesh_bundle_manifest(bundle_id: str):
    """Return manifest.yaml for a specific bundle (for peer download)."""
    manifest = _mesh.get_manifest(bundle_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")
    return manifest


@app.get("/mesh/bundles/{bundle_id}/system_prompt", tags=["Mesh"])
async def mesh_bundle_system_prompt(bundle_id: str):
    """Return system.md for a bundle (for peer download)."""
    import pathlib
    from fastapi.responses import PlainTextResponse
    system_path = pathlib.Path(bundles_dir) / bundle_id / "prompts" / "system.md"
    if not system_path.exists():
        raise HTTPException(status_code=404, detail="system.md not found")
    return PlainTextResponse(system_path.read_text())


class MeshDownloadRequest(BaseModel):
    peer_url: str


@app.post("/mesh/bundles/{bundle_id}/request", tags=["Mesh"])
async def mesh_request_bundle(bundle_id: str, req: MeshDownloadRequest, _auth=Depends(require_auth)):
    """Download a bundle from a peer node. Verifies signature before installing."""
    success = await _mesh.download_bundle(req.peer_url, bundle_id, _crypto)
    if success:
        # Re-index in Qdrant
        try:
            import pathlib
            bundle_path = pathlib.Path(bundles_dir) / bundle_id
            rag.index_bundle(bundle_path)
        except Exception as e:
            logger.warning("Mesh: Qdrant indexing failed for '%s': %s", bundle_id, e)
        return {"status": "installed", "bundle_id": bundle_id, "peer_url": req.peer_url}
    raise HTTPException(status_code=422, detail=f"Failed to download or verify bundle '{bundle_id}'")


@app.get("/mesh/registry", tags=["Mesh"])
async def mesh_registry(_auth=Depends(require_auth)):
    """Return the full distributed bundle registry (local + all known peers)."""
    _registry.refresh_local()
    return _registry.get_all()


# ── Bundle Fusion ─────────────────────────────────────────────────────────────

class FuseRequest(BaseModel):
    bundle_ids: list


@app.post("/bundles/fuse", tags=["Bundles"])
async def fuse_bundles(req: FuseRequest, _auth=Depends(require_admin)):
    """Merge 2+ bundles into a composite fusion bundle. Admin only."""
    if len(req.bundle_ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least 2 bundle_ids")
    try:
        result = _fusion.merge(req.bundle_ids)
        # Index fusion bundle in Qdrant
        try:
            import pathlib
            rag.index_bundle(pathlib.Path(result["path"]))
        except Exception as e:
            logger.warning("Fusion: Qdrant indexing failed: %s", e)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Meta-Agent ────────────────────────────────────────────────────────────────

@app.post("/meta/analyze", tags=["Meta-Agent"])
async def meta_analyze(_auth=Depends(require_admin)):
    """Analyze execution history for unresolved intent patterns. Admin only."""
    patterns = await _meta_agent.analyze_history()
    return {"patterns": patterns, "count": len(patterns)}


@app.get("/meta/suggestions", tags=["Meta-Agent"])
async def meta_suggestions(_auth=Depends(require_admin)):
    """Return pending bundle suggestions from meta-agent. Admin only."""
    suggestions = _meta_agent.get_suggestions()
    return {"suggestions": suggestions, "count": len(suggestions)}


@app.post("/meta/suggestions/{suggestion_id}/create", tags=["Meta-Agent"])
async def meta_create_bundle(suggestion_id: str, _auth=Depends(require_admin)):
    """Create a bundle from a meta-agent suggestion. Admin only."""
    try:
        result = _meta_agent.create_from_suggestion(suggestion_id, builder)
        # Index in Qdrant
        try:
            import pathlib
            rag.index_bundle(pathlib.Path(bundles_dir) / result["bundle_id"])
        except Exception as e:
            logger.warning("MetaAgent: Qdrant indexing failed: %s", e)
        return result
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))



@app.post("/meta/analyze-and-suggest/stream", tags=["Meta-Agent"])
async def meta_analyze_and_suggest_stream(_auth=Depends(require_admin)):
    """Stream meta-agent analysis progress as SSE. Admin only."""
    import json as _json

    async def event_stream():
        try:
            yield "data: " + _json.dumps({"type": "status", "msg": "Analyse de l'historique d'exécution..."}) + "\n\n"
            patterns = await _meta_agent.analyze_history()
            yield "data: " + _json.dumps({"type": "patterns", "msg": f"Trouvé {len(patterns)} pattern(s) non résolus", "count": len(patterns), "patterns": patterns}) + "\n\n"

            if not patterns:
                yield "data: " + _json.dumps({"type": "done", "msg": "Aucun pattern — historique insuffisant", "suggestions": []}) + "\n\n"
                return

            suggestions = []
            for i, pattern in enumerate(patterns[:3]):
                p_name = pattern.get("pattern", str(pattern))
                yield "data: " + _json.dumps({"type": "generating", "msg": f"Génération suggestion {i+1}/{ min(3, len(patterns))} : {p_name[:50]}..."}) + "\n\n"
                try:
                    suggestion = await _meta_agent.suggest_bundle(pattern)
                    if suggestion:
                        sid = _meta_agent.add_suggestion(suggestion)
                        suggestions.append({**suggestion, "id": sid})
                        yield "data: " + _json.dumps({"type": "suggestion", "msg": f"✓ Suggestion créée : {suggestion.get('name','?')}", "suggestion": {**suggestion, "id": sid}}) + "\n\n"
                except Exception as e:
                    yield "data: " + _json.dumps({"type": "error", "msg": f"Erreur génération: {str(e)[:80]}"}) + "\n\n"

            yield "data: " + _json.dumps({"type": "done", "msg": f"Terminé — {len(suggestions)} suggestion(s) créée(s)", "suggestions": suggestions}) + "\n\n"
        except Exception as e:
            yield "data: " + _json.dumps({"type": "error", "msg": f"Erreur critique: {str(e)[:100]}"}) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/meta/analyze-and-suggest", tags=["Meta-Agent"])
async def meta_analyze_and_suggest(_auth=Depends(require_admin)):
    """Analyze history AND generate suggestions via Claude Haiku. Admin only."""
    patterns = await _meta_agent.analyze_history()
    suggestions = []
    for pattern in patterns[:3]:  # Limit to 3 suggestions per call to control costs
        suggestion = await _meta_agent.suggest_bundle(pattern)
        if suggestion:
            sid = _meta_agent.add_suggestion(suggestion)
            suggestions.append(suggestion)
    return {"patterns_analyzed": len(patterns), "suggestions_created": len(suggestions), "suggestions": suggestions}


# ── Factory Health & Rebuild ──────────────────────────────────────────────────

@app.get("/factory/health", tags=["Factory"])
async def factory_health(_auth=Depends(require_admin)):
    """Return health report for all bundles. Admin only."""
    import pathlib
    bdir = pathlib.Path(bundles_dir)
    reports = []
    for bundle_dir in sorted(bdir.iterdir()):
        if bundle_dir.is_dir() and (bundle_dir / "manifest.yaml").exists():
            try:
                report = _evaluator_p3.get_bundle_health(bundle_dir)
                reports.append(report)
            except Exception as e:
                reports.append({"id": bundle_dir.name, "error": str(e)})
    return {"bundles": reports, "count": len(reports)}


@app.post("/factory/rebuild/{bundle_id}", tags=["Factory"])
async def factory_rebuild_bundle(bundle_id: str, _auth=Depends(require_admin)):
    """Regenerate bundle system.md via Claude Haiku using usage history context. Admin only."""
    import pathlib
    bundle_path = pathlib.Path(bundles_dir) / bundle_id
    if not bundle_path.exists():
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")

    api_key = None
    key_file = pathlib.Path("/app/secrets_vault/anthropic_key.txt")
    if key_file.exists():
        api_key = key_file.read_text().strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    import yaml, time
    manifest = yaml.safe_load((bundle_path / "manifest.yaml").read_text())
    name = manifest.get("name", bundle_id)
    caps = manifest.get("capabilities", [])

    prompt = f"""Tu es un expert en rédaction de system prompts pour agents IA spécialisés.

Régénère le system prompt pour le bundle BundleFabric suivant :
- Nom : {name}
- Capabilities : {', '.join(caps)}
- Date de rebuild : {time.strftime('%Y-%m-%d')}

Génère un system prompt professionnel, complet et à jour (3-5 paragraphes).
Commence directement par le contenu, sans titre ni introduction."""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5", "max_tokens": 1024,
                      "messages": [{"role": "user", "content": prompt}]},
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Claude error: {resp.status_code}")
            new_prompt = resp.json()["content"][0]["text"].strip()

        (bundle_path / "prompts").mkdir(exist_ok=True)
        (bundle_path / "prompts" / "system.md").write_text(new_prompt)

        # Update manifest rebuilt_at
        manifest.setdefault("meta", {})["last_rebuilt_at"] = time.strftime("%Y-%m-%d")
        (bundle_path / "manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
        )

        # Re-index in Qdrant
        try:
            rag.index_bundle(bundle_path)
        except Exception:
            pass

        return {"status": "rebuilt", "bundle_id": bundle_id, "system_md_length": len(new_prompt)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ── Prometheus metrics ────────────────────────────────────────────────────────

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Prometheus metrics endpoint — bundle TPS, usage, executions."""
    import pathlib
    import yaml as _yaml
    # Refresh TPS gauges from bundle manifests
    try:
        bdir = pathlib.Path(bundles_dir)
        count = 0
        for bdir_item in sorted(bdir.iterdir()):
            if bdir_item.is_dir() and (bdir_item / "manifest.yaml").exists():
                try:
                    manifest = _yaml.safe_load((bdir_item / "manifest.yaml").read_text())
                    bid = bdir_item.name
                    temporal = manifest.get("temporal", {})
                    freshness = temporal.get("freshness_score", 0.5)
                    ecosystem = temporal.get("ecosystem_alignment", 0.5)
                    usage_freq = temporal.get("usage_frequency", 0.0)
                    # TPS = freshness*0.4 + usage_freq*0.3 + ecosystem*0.3
                    tps = freshness * 0.4 + usage_freq * 0.3 + ecosystem * 0.3
                    usage = temporal.get("usage_count", 0)
                    _tps_gauge.labels(bundle_id=bid).set(tps)
                    _usage_gauge.labels(bundle_id=bid).set(usage)
                    count += 1
                except Exception:
                    pass
        _bundles_loaded.set(count)
    except Exception:
        pass
    return _Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# ── Admin routes ─────────────────────────────────────────────────────────────

@app.get("/admin/users", tags=["Admin"])
async def admin_list_users(_auth=Depends(require_admin)):
    """List all users (api_key masked). Admin only."""
    users = list_users()
    # Mask api_key in response
    return {"count": len(users), "users": [
        {"username": u["username"], "role": u["role"], "api_key_masked": u["api_key_masked"]}
        for u in users
    ]}


@app.post("/admin/users", tags=["Admin"])
async def admin_create_user(req: CreateUserRequest, _auth=Depends(require_admin)):
    """Create a new user with generated API key. Returns key in clear — store it now."""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")
    try:
        user = create_user(req.username, req.role)
        return {"status": "created", "username": user["username"],
                "api_key": user["api_key"], "role": user["role"],
                "warning": "Store this api_key now — it will not be shown again"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.delete("/admin/users/{username}", tags=["Admin"])
async def admin_delete_user(username: str, _auth=Depends(require_admin)):
    """Delete a user. Cannot delete yourself."""
    if username == _auth.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    deleted = delete_user(username)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    return {"status": "deleted", "username": username}


# ── Auth routes ─────────────────────────────────────────────────────────────

@app.post("/auth/token", tags=["Auth"])
async def get_token(req: TokenRequest):
    """Exchange API key for JWT token (24h expiry)."""
    result = create_token(req.api_key)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return result


# ── System routes ────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": VERSION,
            "uptime_seconds": round(time.time() - START_TIME, 1)}


@app.get("/status", tags=["System"])
async def status():
    deerflow_status = await deerflow.health_check()
    bundle_count = len(loader.list_bundle_ids())
    return {
        "status": "ok",
        "version": VERSION,
        "bundles_loaded": bundle_count,
        "deerflow": deerflow_status,
        "qdrant_available": rag.is_available,
        "qdrant_indexed_count": _rag_indexed_count,
        "qdrant_total_bundles": _rag_total_count,
        "ollama_url": os.getenv("OLLAMA_URL", "http://ollama:11434"),
        "claude_available": _claude_available,
        "claude_tailscale_only": True,
        "streaming_available": _claude_available,
    }


# ── Bundle routes ─────────────────────────────────────────────────────────────

@app.get("/bundles", tags=["Bundles"])
async def list_bundles():
    bundles = loader.list_bundles()
    return {"count": len(bundles), "bundles": [b.to_summary() for b in bundles]}


@app.get("/bundles/{bundle_id}", tags=["Bundles"])
async def get_bundle(bundle_id: str):
    try:
        bundle = loader.load_bundle(bundle_id)
        return bundle.model_dump()
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")


@app.get("/bundles/{bundle_id}/capabilities", tags=["Bundles"])
async def get_bundle_capabilities(bundle_id: str):
    """Return lightweight capabilities, keywords and domains for a bundle. Public."""
    try:
        bundle = loader.load_bundle(bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")
    return {
        "bundle_id": bundle_id,
        "name": bundle.name,
        "capabilities": bundle.capabilities,
        "keywords": bundle.keywords,
        "domains": bundle.domains,
    }


@app.get("/bundles/{bundle_id}/stats", tags=["Bundles"])
async def get_bundle_stats_endpoint(bundle_id: str):
    """Return execution statistics for a bundle (usage_count, last_executed, success_rate). Public."""
    try:
        bundle = loader.load_bundle(bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")
    stats = await get_bundle_stats(bundle_id)
    return {
        "bundle_id": bundle_id,
        "name": bundle.name,
        "tps_score": bundle.temporal.tps_score,
        **stats,
    }


@app.post("/bundles/create", tags=["Bundles"])
async def create_bundle(req: CreateBundleRequest, _auth=Depends(require_auth)):
    if loader.bundle_exists(req.id):
        raise HTTPException(status_code=409, detail=f"Bundle '{req.id}' already exists")
    try:
        manifest = builder.scaffold_bundle(
            bundle_id=req.id, name=req.name, description=req.description,
            capabilities=req.capabilities, domains=req.domains, keywords=req.keywords,
            version=req.version, author=req.author, freshness_score=req.freshness_score,
        )
        asyncio.create_task(_index_single_bundle(manifest))
        return {"status": "created", "bundle": manifest.to_summary()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/bundles/{bundle_id}", tags=["Bundles"])
async def update_bundle(bundle_id: str, req: UpdateBundleRequest, _auth=Depends(require_auth)):
    """Update bundle fields (partial update). Protected."""
    try:
        updates = req.model_dump(exclude_none=True)
        updated = loader.update_bundle(bundle_id, updates)
        return {"status": "updated", "bundle": updated.to_summary()}
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/bundles/{bundle_id}", tags=["Bundles"])
async def delete_bundle(bundle_id: str, _auth=Depends(require_auth)):
    """Delete a bundle and its directory. Protected."""
    try:
        loader.delete_bundle(bundle_id)
        return {"status": "deleted", "bundle_id": bundle_id}
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")


async def _index_single_bundle(bundle: BundleManifest) -> None:
    global _rag_indexed_count, _rag_total_count
    try:
        rag.ensure_collection()
        if rag.index_bundle(bundle):
            _rag_indexed_count += 1
            _rag_total_count += 1
    except Exception as e:
        logger.warning("RAG: failed to index new bundle '%s': %s", bundle.id, e)


# ── Orchestration routes ──────────────────────────────────────────────────────

@app.post("/intent", tags=["Orchestration"])
async def extract_intent(req: IntentRequest, request: Request):
    tailscale_ok = request.headers.get("X-Tailscale-Access") == "1"
    use_claude = req.use_claude and tailscale_ok
    intent = await intent_engine.extract(req.text, use_ollama=req.use_ollama, use_claude=use_claude)
    return intent.model_dump()


@app.post("/resolve", tags=["Orchestration"])
async def resolve_bundles(req: ResolveRequest):
    try:
        intent = Intent(**req.intent)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid intent: {e}")
    matches = resolver.find_matches(intent, top_k=req.top_k, filter_archival=req.filter_archival)
    return {"intent_goal": intent.goal, "matches_count": len(matches),
            "matches": [m.model_dump() for m in matches]}


@app.post("/execute/dry-run", tags=["Orchestration"])
async def execute_dry_run(req: DryRunRequest):
    """Resolve intent and generate system prompt WITHOUT calling DeerFlow. Public."""
    try:
        bundle = loader.load_bundle(req.bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{req.bundle_id}' not found")
    intent = await intent_engine.extract(req.intent_text)
    from orchestrator.deerflow_client import _build_system_prompt
    system_prompt = _build_system_prompt(bundle)
    return {
        "bundle_id": req.bundle_id,
        "intent_text": req.intent_text,
        "goal": intent.goal,
        "system_prompt": system_prompt,
        "dry_run": True,
    }


@app.post("/execute", tags=["Orchestration"])
async def execute_bundle(req: ExecuteRequest, _auth=Depends(require_auth)):
    """Execute a bundle via DeerFlow. Records history and increments TPS."""
    try:
        bundle = loader.load_bundle(req.bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{req.bundle_id}' not found")

    start_ms = int(time.time() * 1000)
    intent = await intent_engine.extract(req.intent_text)
    result = await deerflow.execute_bundle(
        bundle_id=req.bundle_id, intent=intent,
        workflow_id=req.workflow_id or bundle.deerflow_workflow, bundle=bundle,
    )
    duration_ms = int(time.time() * 1000) - start_ms

    # Persist history (non-blocking)
    asyncio.create_task(record_execution(
        bundle_id=req.bundle_id, bundle_name=bundle.name, intent_text=req.intent_text,
        goal=intent.goal, status=result.status, output=result.output,
        error_message=result.error_message, duration_ms=duration_ms,
    ))
    # Increment TPS usage (non-blocking)
    asyncio.get_event_loop().run_in_executor(None, loader.increment_usage, req.bundle_id)

    return result.model_dump()


@app.post("/execute/stream", tags=["Orchestration"])
async def execute_bundle_stream(req: ExecuteRequest, request: Request, _auth=Depends(require_auth)):
    """Stream bundle execution via Claude Haiku SSE. Tailscale-only. Protected."""
    tailscale_ok = request.headers.get("X-Tailscale-Access") == "1"
    if not tailscale_ok:
        raise HTTPException(status_code=403, detail="Streaming requires Tailscale access")

    try:
        bundle = loader.load_bundle(req.bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{req.bundle_id}' not found")

    from orchestrator.deerflow_client import _build_system_prompt
    system_prompt = _build_system_prompt(bundle)
    start_ms = int(time.time() * 1000)

    async def sse_generator():
        full_output = ""
        status = "success"
        error_msg = None
        try:
            async for chunk in _claude_execute_stream(
                intent_text=req.intent_text,
                system_prompt=system_prompt,
                bundle_id=req.bundle_id,
                bundle_name=bundle.name,
            ):
                yield chunk
                if chunk.startswith("data:") and "token" in chunk:
                    try:
                        import json as _j
                        d = _j.loads(chunk[5:].strip())
                        if d.get("type") == "token":
                            full_output += d.get("content", "")
                    except Exception:
                        pass
                if chunk.startswith("event: error"):
                    status = "error"
                    error_msg = "Claude stream error"
        except Exception as e:
            error_msg = str(e)
            status = "error"

        duration_ms = int(time.time() * 1000) - start_ms
        asyncio.create_task(record_execution(
            bundle_id=req.bundle_id, bundle_name=bundle.name, intent_text=req.intent_text,
            goal=req.intent_text[:200], status=status, output=full_output,
            error_message=error_msg, duration_ms=duration_ms,
        ))
        asyncio.get_event_loop().run_in_executor(None, loader.increment_usage, req.bundle_id)

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/execute/deerflow/stream", tags=["Orchestration"])
async def execute_deerflow_stream(req: ExecuteRequest, _auth=Depends(require_auth)):
    """
    Stream bundle execution via DeerFlow LangGraph (real integration).
    Uses deer-flow-langgraph:2024 threads/runs/stream SSE API.
    Falls back to Claude Haiku if LangGraph is unavailable or times out.
    """
    try:
        bundle = loader.load_bundle(req.bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{req.bundle_id}' not found")

    from orchestrator.deerflow_client import _build_system_prompt
    system_prompt = _build_system_prompt(bundle)
    start_ms = int(time.time() * 1000)

    async def sse_generator():
        import json  # ensure json available in nested generator scope
        full_output = ""
        status = "success"
        error_msg = None
        used_fallback = False
        langgraph_failed = False

        # Fast intent extraction (skip Ollama to not block the SSE stream)
        # Ollama takes 30-90s on CPU-only — use keyword extraction instead
        try:
            from orchestrator.intent_engine import extract_fast as _extract_fast
            intent_obj = _extract_fast(req.intent_text)
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': f'Intent extraction failed: {e}'})}\n\n"
            return

        # ── Phase 1: Try DeerFlow LangGraph ──────────────────────────────────
        yield f"data: {json.dumps({'type': 'status', 'msg': '🦌 Connexion DeerFlow LangGraph…', 'engine': 'langgraph'})}\n\n"

        try:
            token_count = 0
            error_seen = False
            async for chunk in deerflow.execute_bundle_stream(
                bundle_id=req.bundle_id,
                intent=intent_obj,
                workflow_id=req.workflow_id,
                bundle=bundle,
            ):
                # Forward the chunk
                yield chunk

                # Track tokens
                if "token" in chunk and '"content"' in chunk:
                    try:
                        import json as _j
                        d = _j.loads(chunk[5:].strip()) if chunk.startswith("data:") else {}
                        if d.get("type") == "token":
                            full_output += d.get("content", "")
                            token_count += 1
                    except Exception:
                        pass

                # Detect error
                if chunk.startswith("event: error"):
                    error_seen = True
                    langgraph_failed = True
                    break

            if error_seen or token_count == 0:
                langgraph_failed = True

        except Exception as e:
            langgraph_failed = True
            yield f"data: {json.dumps({'type': 'warning', 'msg': f'DeerFlow exception: {str(e)[:80]}'})}\n\n"

        # ── Phase 2: Fallback to Claude Haiku if DeerFlow produced nothing ───
        if langgraph_failed or not full_output.strip():
            used_fallback = True
            full_output = ""
            yield f"data: {json.dumps({'type': 'status', 'msg': '⚡ Fallback Claude Haiku…', 'engine': 'claude_haiku'})}\n\n"
            try:
                async for chunk in _claude_execute_stream(
                    intent_text=req.intent_text,
                    system_prompt=system_prompt,
                    bundle_id=req.bundle_id,
                    bundle_name=bundle.name,
                ):
                    yield chunk
                    if chunk.startswith("data:") and "token" in chunk:
                        try:
                            import json as _j
                            d = _j.loads(chunk[5:].strip())
                            if d.get("type") == "token":
                                full_output += d.get("content", "")
                        except Exception:
                            pass
                    if chunk.startswith("event: error"):
                        status = "error"
                        error_msg = "Claude Haiku fallback error"
            except Exception as e:
                status = "error"
                error_msg = str(e)
                yield f"event: error\ndata: {json.dumps({'message': f'Claude fallback failed: {e}'})}\n\n"
                return

        # ── Record + TPS ─────────────────────────────────────────────────────
        duration_ms = int(time.time() * 1000) - start_ms
        engine_used = "claude_haiku_fallback" if used_fallback else "langgraph"
        asyncio.create_task(record_execution(
            bundle_id=req.bundle_id, bundle_name=bundle.name, intent_text=req.intent_text,
            goal=intent_obj.goal, status=status, output=full_output,
            error_message=error_msg, duration_ms=duration_ms,
        ))
        asyncio.get_event_loop().run_in_executor(None, loader.increment_usage, req.bundle_id)

        yield f"data: {json.dumps({'type': 'summary', 'engine': engine_used, 'duration_ms': duration_ms, 'output_length': len(full_output)})}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── History routes ────────────────────────────────────────────────────────────

@app.get("/history", tags=["History"])
async def list_history(bundle_id: Optional[str] = None, limit: int = 50):
    """Return execution history (public, read-only)."""
    rows = await get_history(bundle_id=bundle_id, limit=min(limit, 200))
    return {"count": len(rows), "executions": rows}


@app.get("/history/search", tags=["History"])
async def search_history_endpoint(q: str, limit: int = 50):
    """Full-text search on intent_text and goal. Must be defined before /history/{exec_id}."""
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="Query 'q' must be at least 2 characters")
    rows = await search_history(q.strip(), limit=min(limit, 200))
    return {"query": q, "count": len(rows), "executions": rows}


@app.get("/history/{exec_id}", tags=["History"])
async def get_execution_by_id(exec_id: int):
    row = await get_execution(exec_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Execution {exec_id} not found")
    return row


# ── DeerFlow ──────────────────────────────────────────────────────────────────

@app.get("/deerflow/status", tags=["DeerFlow"])
async def deerflow_status():
    return await deerflow.health_check()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
