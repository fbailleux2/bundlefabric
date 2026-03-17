"""BundleFabric Memory — Qdrant RAG interface."""
from __future__ import annotations
import os
import uuid
from typing import List, Optional, Dict, Any

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleManifest

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
                print(f"Qdrant unavailable: {e}")
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
            return True
        except Exception as e:
            print(f"ensure_collection error: {e}")
            return False

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get text embedding via Ollama nomic-embed-text."""
        try:
            import httpx
            resp = httpx.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=15.0,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as e:
            print(f"Embedding error: {e}")
            return None

    def index_bundle(self, bundle: BundleManifest) -> bool:
        """Index a bundle manifest in Qdrant for semantic search."""
        client = self._get_client()
        if not client:
            return False

        self.ensure_collection(COLLECTION_MANIFESTS)

        # Build text representation for embedding
        text = (
            f"{bundle.name}. {bundle.description}. "
            f"Capabilities: {', '.join(bundle.capabilities)}. "
            f"Domains: {', '.join(bundle.domains)}. "
            f"Keywords: {', '.join(bundle.keywords)}."
        )

        embedding = self._get_embedding(text)
        if not embedding:
            return False

        try:
            from qdrant_client.models import PointStruct
            client.upsert(
                collection_name=COLLECTION_MANIFESTS,
                points=[PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, bundle.id)),
                    vector=embedding,
                    payload={
                        "bundle_id": bundle.id,
                        "name": bundle.name,
                        "description": bundle.description,
                        "capabilities": bundle.capabilities,
                        "domains": bundle.domains,
                        "tps_score": bundle.temporal.tps_score,
                        "status": bundle.temporal.status.value,
                    },
                )],
            )
            return True
        except Exception as e:
            print(f"index_bundle error: {e}")
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
            print(f"search error: {e}")
            return []

    @property
    def is_available(self) -> bool:
        """Check if Qdrant is reachable."""
        client = self._get_client()
        return self._available
