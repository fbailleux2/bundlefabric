"""BundleFabric Orchestrator — FastAPI main application."""
from __future__ import annotations
import os
import sys
import time
from typing import List, Optional, Dict, Any

sys.path.insert(0, "/opt/bundlefabric")

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models.bundle import BundleManifest
from models.intent import Intent, BundleMatch, ExecutionResult
from factory.loader import BundleLoader, BundleNotFoundError
from factory.builder import BundleBuilder
from factory.evaluator import BundleEvaluator
from orchestrator.intent_engine import IntentEngine
from orchestrator.bundle_resolver import BundleResolver
from orchestrator.deerflow_client import DeerFlowClient
from memory.rag_manager import RAGManager

VERSION = "2.0.0"
START_TIME = time.time()

app = FastAPI(
    title="BundleFabric API",
    description="Cognitive OS Orchestrator — intent → bundle → DeerFlow",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow bundlefabric.org domains + localhost for dev
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

# Singletons
loader = BundleLoader()
builder = BundleBuilder()
evaluator = BundleEvaluator()
intent_engine = IntentEngine(use_ollama=os.getenv("USE_OLLAMA", "true").lower() == "true")
resolver = BundleResolver(loader=loader)
deerflow = DeerFlowClient()
rag = RAGManager()


# ── Request/Response models ─────────────────────────────────────────────────

class IntentRequest(BaseModel):
    text: str
    use_ollama: bool = True


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


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    """Health check — returns API status and version."""
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/status", tags=["System"])
async def status():
    """Extended status — all subsystem states."""
    deerflow_status = await deerflow.health_check()
    bundle_count = len(loader.list_bundle_ids())
    return {
        "status": "ok",
        "version": VERSION,
        "bundles_loaded": bundle_count,
        "deerflow": deerflow_status,
        "qdrant_available": rag.is_available,
        "ollama_url": os.getenv("OLLAMA_URL", "http://127.0.0.1:18630"),
    }


@app.get("/bundles", tags=["Bundles"])
async def list_bundles():
    """List all bundles with TPS scores and status."""
    bundles = loader.list_bundles()
    return {
        "count": len(bundles),
        "bundles": [b.to_summary() for b in bundles],
    }


@app.get("/bundles/{bundle_id}", tags=["Bundles"])
async def get_bundle(bundle_id: str):
    """Get full bundle details by ID."""
    try:
        bundle = loader.load_bundle(bundle_id)
        return bundle.model_dump()
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found")


@app.post("/bundles/create", tags=["Bundles"])
async def create_bundle(req: CreateBundleRequest):
    """Create a new bundle via the Factory scaffold system."""
    if loader.bundle_exists(req.id):
        raise HTTPException(status_code=409, detail=f"Bundle '{req.id}' already exists")
    try:
        manifest = builder.scaffold_bundle(
            bundle_id=req.id,
            name=req.name,
            description=req.description,
            capabilities=req.capabilities,
            domains=req.domains,
            keywords=req.keywords,
            version=req.version,
            author=req.author,
            freshness_score=req.freshness_score,
        )
        return {"status": "created", "bundle": manifest.to_summary()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/intent", tags=["Orchestration"])
async def extract_intent(req: IntentRequest):
    """Extract structured intent from free text."""
    intent = await intent_engine.extract(req.text)
    return intent.model_dump()


@app.post("/resolve", tags=["Orchestration"])
async def resolve_bundles(req: ResolveRequest):
    """Resolve best matching bundles for a given intent."""
    try:
        intent = Intent(**req.intent)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid intent: {e}")

    matches = resolver.find_matches(
        intent,
        top_k=req.top_k,
        filter_archival=req.filter_archival,
    )
    return {
        "intent_goal": intent.goal,
        "matches_count": len(matches),
        "matches": [m.model_dump() for m in matches],
    }


@app.post("/execute", tags=["Orchestration"])
async def execute_bundle(req: ExecuteRequest):
    """Execute a bundle via DeerFlow engine."""
    try:
        bundle = loader.load_bundle(req.bundle_id)
    except BundleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Bundle '{req.bundle_id}' not found")

    intent = await intent_engine.extract(req.intent_text)
    result = await deerflow.execute_bundle(
        bundle_id=req.bundle_id,
        intent=intent,
        workflow_id=req.workflow_id or bundle.deerflow_workflow,
    )
    return result.model_dump()


@app.get("/deerflow/status", tags=["DeerFlow"])
async def deerflow_status():
    """Get DeerFlow engine health status."""
    return await deerflow.health_check()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
