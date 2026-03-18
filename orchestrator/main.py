"""BundleFabric Orchestrator — FastAPI main application."""
from __future__ import annotations
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

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
from memory.history_manager import init_db, record_execution, get_history, get_execution
from auth.jwt_auth import require_auth, require_admin, create_token, list_users, create_user, delete_user, rotate_jwt_secret

VERSION = "2.1.0"
START_TIME = time.time()

# ── Singletons ──────────────────────────────────────────────────────────────
loader = BundleLoader()
builder = BundleBuilder()
evaluator = BundleEvaluator()
intent_engine = IntentEngine(use_ollama=os.getenv("USE_OLLAMA", "true").lower() == "true")
resolver = BundleResolver(loader=loader)
deerflow = DeerFlowClient()
rag = RAGManager()

_rag_indexed_count: int = 0
_rag_total_count: int = 0


async def _startup_index_bundles() -> None:
    global _rag_indexed_count, _rag_total_count
    await asyncio.sleep(2)
    try:
        bundles = loader.list_bundles()
        _rag_total_count = len(bundles)
        if not bundles:
            print("[RAG] No bundles to index.")
            return
        rag.ensure_collection()
        indexed = 0
        for bundle in bundles:
            try:
                if rag.index_bundle(bundle):
                    indexed += 1
            except Exception as e:
                print(f"[RAG] Failed to index {bundle.id}: {e}")
        _rag_indexed_count = indexed
        print(f"[RAG] Indexed {indexed}/{len(bundles)} bundles into Qdrant.")
    except Exception as e:
        print(f"[RAG] Startup indexing error (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_startup_index_bundles())
    await init_db()
    print(f"[Startup] BundleFabric API v{VERSION} starting...")
    yield
    task.cancel()
    print("[Shutdown] BundleFabric API stopped.")


import auth.oauth_router as _oauth_router

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

app.include_router(_oauth_router.router)


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
        print(f"[RAG] Failed to index new bundle {bundle.id}: {e}")


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

# ── History routes ────────────────────────────────────────────────────────────

@app.get("/history", tags=["History"])
async def list_history(bundle_id: Optional[str] = None, limit: int = 50):
    """Return execution history (public, read-only)."""
    rows = await get_history(bundle_id=bundle_id, limit=min(limit, 200))
    return {"count": len(rows), "executions": rows}


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
