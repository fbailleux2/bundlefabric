"""BundleFabric Memory — Qdrant RAG interface.

Manages semantic search over bundle manifests using:
  - Qdrant as the vector store
  - Ollama nomic-embed-text for 768-dim embeddings (~7-9s per embedding on CPU)
  - Cosine similarity for bundle retrieval
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleManifest
from logging_config import get_logger

logger = get_logger("memory.rag")

QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:18650")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:18630")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_MANIFESTS = "bundle_manifests"
COLLECTION_RAG = "bundle_rag"
VECTOR_SIZE = 768  # nomic-embed-text output dimension


class RAGManager:
    """Interface to Qdrant for bundle semantic search and indexing."""

    def __init__(self):
        self._client = None
        self._available = False

    def _get_client(self):
        """Lazy-init Qdrant client."""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(url=QDRANT_URL, timeout=10)
                self._available = True
            except Exception as e:
                logger.warning("Qdrant unavailable — RAG disabled: %s", e)
                self._available = False
        return self._client

    def ensure_collection(self, collection_name: str = COLLECTION_MANIFESTS) -> bool:
        """Create Qdrant collection if it doesn't exist. Returns True on success."""
        client = self._get_client()
        if not client:
            return False
        try:
            from qdrant_client.models import Distance, VectorParams
            existing = [c.name for c in client.get_collections().collections]
            if collection_name not in existing:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info("Qdrant collection created — name=%s vector_size=%d", collection_name, VECTOR_SIZE)
            else:
                logger.debug("Qdrant collection exists — name=%s", collection_name)
            return True
        except Exception as e:
            logger.error("ensure_collection failed for '%s': %s", collection_name, e)
            return False

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get text embedding via Ollama nomic-embed-text.

        Note: on CPU-only hardware (Haswell), each call takes ~7-9s.
        Embeddings are computed at startup (indexing) and per search query.
        """
        t0 = time.time()
        try:
            import httpx
            resp = httpx.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=15.0,
            )
            resp.raise_for_status()
            embedding = resp.json()["embedding"]
            logger.debug(
                "Embedding generated in %.1fs — model=%s text_len=%d dim=%d",
                time.time() - t0, EMBED_MODEL, len(text), len(embedding),
            )
            return embedding
        except Exception as e:
            logger.warning("Embedding request failed after %.1fs: %s", time.time() - t0, e)
            return None

    def index_bundle(self, bundle: Union[BundleManifest, Path]) -> bool:
        """Index a bundle in Qdrant for semantic search.

        Accepts either a BundleManifest object or a pathlib.Path to the bundle
        directory — the manifest is loaded automatically from the Path.
        This dual-accept signature fixes a bug where mesh/fusion routes passed
        Path objects while the method expected BundleManifest.
        """
        # Accept Path → load manifest automatically (callers may pass a bundle directory)
        if isinstance(bundle, Path):
            manifest_path = bundle / "manifest.yaml"
            if not manifest_path.exists():
                logger.warning("index_bundle: no manifest.yaml at %s", bundle)
                return False
            try:
                import yaml
                data = yaml.safe_load(manifest_path.read_text())
                if "temporal" not in data:
                    data["temporal"] = {"freshness_score": 0.5}
                bundle = BundleManifest(**data)
            except Exception as exc:
                logger.error("index_bundle: failed to load manifest from %s: %s", bundle, exc)
                return False

        client = self._get_client()
        if not client:
            return False

        self.ensure_collection(COLLECTION_MANIFESTS)

        # Build text representation combining all searchable fields for the embedding
        text = (
            f"{bundle.name}. {bundle.description}. "
            f"Capabilities: {', '.join(bundle.capabilities)}. "
            f"Domains: {', '.join(bundle.domains)}. "
            f"Keywords: {', '.join(bundle.keywords)}."
        )

        embedding = self._get_embedding(text)
        if not embedding:
            logger.warning("index_bundle: embedding failed for '%s' — not indexed", bundle.id)
            return False

        try:
            from qdrant_client.models import PointStruct
            client.upsert(
                collection_name=COLLECTION_MANIFESTS,
                points=[PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, bundle.id)),
                    vector=embedding,
                    payload={
                        "bundle_id":    bundle.id,
                        "name":         bundle.name,
                        "description":  bundle.description,
                        "capabilities": bundle.capabilities,
                        "domains":      bundle.domains,
                        "tps_score":    bundle.temporal.tps_score,
                        "status":       bundle.temporal.status.value,
                    },
                )],
            )
            logger.info("Bundle indexed in Qdrant — id=%s tps=%.3f", bundle.id, bundle.temporal.tps_score)
            return True
        except Exception as exc:
            logger.error("index_bundle upsert failed for '%s': %s", bundle.id, exc)
            return False

    def search(
        self,
        query: str,
        collection_name: str = COLLECTION_MANIFESTS,
        top_k: int = 5,
        score_threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """Search Qdrant for semantically similar bundles."""
        client = self._get_client()
        if not client:
            return []

        embedding = self._get_embedding(query)
        if not embedding:
            return []

        logger.debug("Qdrant search — query_len=%d top_k=%d threshold=%.2f", len(query), top_k, score_threshold)
        try:
            results = client.search(
                collection_name=collection_name,
                query_vector=embedding,
                limit=top_k,
                score_threshold=score_threshold,
            )
            return [
                {
                    "bundle_id": r.payload.get("bundle_id"),
                    "name": r.payload.get("name"),
                    "score": r.score,
                    "tps_score": r.payload.get("tps_score", 0),
                    "status": r.payload.get("status"),
                    "capabilities": r.payload.get("capabilities", []),
                }
                for r in results
            ]
        except Exception as e:
            logger.error("Qdrant search failed — collection=%s: %s", collection_name, e)
            return []

    @property
    def is_available(self) -> bool:
        """Check if Qdrant is reachable."""
        client = self._get_client()
        return self._available
