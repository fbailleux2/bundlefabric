"""BundleFabric — Distributed bundle registry (local + mesh peers)."""
from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any, Dict, List, Optional

import yaml

_DATA_DIR = pathlib.Path(
    os.getenv("HISTORY_DB", "/app/data/history.db")
).parent
_REGISTRY_FILE = _DATA_DIR / "mesh_registry.json"
_BUNDLES_DIR = pathlib.Path(os.getenv("BUNDLES_DIR", "/app/bundles"))


class BundleRegistry:
    """Local + mesh bundle index. Persisted in data/mesh_registry.json."""

    def __init__(
        self,
        registry_file: pathlib.Path | None = None,
        bundles_dir: pathlib.Path | None = None,
    ):
        self._file = registry_file or _REGISTRY_FILE
        self._bundles_dir = bundles_dir or _BUNDLES_DIR
        self._index: Dict[str, Any] = {"local": [], "peers": {}}
        self.load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load registry from file if it exists."""
        if self._file.exists():
            try:
                self._index = json.loads(self._file.read_text())
            except Exception as e:
                print(f"[Registry] Failed to load registry: {e}")
                self._index = {"local": [], "peers": {}}

    def save(self) -> None:
        """Persist registry to file."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._index, indent=2, ensure_ascii=False))

    # ── Local bundles ──────────────────────────────────────────────────────────

    def refresh_local(self, bundles_dir: pathlib.Path | None = None) -> int:
        """Scan bundles directory and update local index. Returns bundle count."""
        bdir = bundles_dir or self._bundles_dir
        local_bundles = []

        if not bdir.exists():
            self._index["local"] = []
            return 0

        for bundle_dir in sorted(bdir.iterdir()):
            manifest_path = bundle_dir / "manifest.yaml"
            if not manifest_path.exists():
                continue
            try:
                manifest = yaml.safe_load(manifest_path.read_text())
                signed = (bundle_dir / "signatures" / "bundle.sig").exists()
                tps = 0.0
                temporal = manifest.get("temporal", {})
                if temporal:
                    f = float(temporal.get("freshness_score", 0.5))
                    u = float(temporal.get("usage_frequency", 0.0))
                    e = float(temporal.get("ecosystem_alignment", 0.5))
                    tps = round(f * 0.4 + u * 0.3 + e * 0.3, 3)
                local_bundles.append({
                    "id": manifest.get("id", bundle_dir.name),
                    "name": manifest.get("name", bundle_dir.name),
                    "description": manifest.get("description", ""),
                    "capabilities": manifest.get("capabilities", []),
                    "tps": tps,
                    "signed": signed,
                    "public": manifest.get("public", False),
                    "fusion": "fusion_sources" in manifest,
                    "source": "local",
                })
            except Exception as e:
                print(f"[Registry] Skipped {bundle_dir.name}: {e}")

        self._index["local"] = local_bundles
        self.save()
        return len(local_bundles)

    # ── Peer management ────────────────────────────────────────────────────────

    def add_peer(self, url: str, bundles_list: List[Dict]) -> None:
        """Add or update a peer in the registry."""
        self._index["peers"][url] = {
            "last_seen": time.time(),
            "bundles": bundles_list,
        }
        self.save()

    def get_peer_bundles(self, url: str) -> List[Dict]:
        """Return bundles from a specific peer."""
        peer = self._index["peers"].get(url, {})
        return peer.get("bundles", [])

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, query: str) -> List[Dict]:
        """Search bundles across local + peers by name, description, or capabilities."""
        query_lower = query.lower()
        results = []

        for bundle in self.get_local():
            score = 0
            if query_lower in bundle.get("id", "").lower():
                score += 3
            if query_lower in bundle.get("name", "").lower():
                score += 3
            if query_lower in bundle.get("description", "").lower():
                score += 1
            if any(query_lower in cap.lower() for cap in bundle.get("capabilities", [])):
                score += 2
            if score > 0:
                results.append({**bundle, "_score": score})

        for peer_url, peer_data in self._index["peers"].items():
            for bundle in peer_data.get("bundles", []):
                score = 0
                if query_lower in bundle.get("id", "").lower():
                    score += 3
                if query_lower in bundle.get("name", "").lower():
                    score += 3
                if any(query_lower in cap.lower() for cap in bundle.get("capabilities", [])):
                    score += 2
                if score > 0:
                    results.append({**bundle, "source": "mesh", "peer_url": peer_url, "_score": score})

        return sorted(results, key=lambda x: x["_score"], reverse=True)

    # ── Accessors ──────────────────────────────────────────────────────────────

    def get_all(self) -> Dict[str, Any]:
        """Return full registry index."""
        return self._index

    def get_local(self) -> List[Dict]:
        """Return local bundles only."""
        return self._index.get("local", [])

    def get_public(self) -> List[Dict]:
        """Return bundles marked public:true."""
        return [b for b in self.get_local() if b.get("public", False)]

    def get_peer_count(self) -> int:
        return len(self._index.get("peers", {}))

    def get_local_bundle_count(self) -> int:
        return len(self._index.get("local", []))
