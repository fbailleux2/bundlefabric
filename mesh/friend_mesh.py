"""BundleFabric — Friend Mesh P2P over HTTP gossip."""
from __future__ import annotations

import os
import pathlib
from typing import Any, Dict, List, Optional

import httpx
import yaml

_FRIENDS_CONFIG = os.getenv("FRIENDS_CONFIG", "/app/friends.yaml")
_BUNDLES_DIR = pathlib.Path(os.getenv("BUNDLES_DIR", "/app/bundles"))
MESH_ENABLED = os.getenv("MESH_ENABLED", "false").lower() == "true"


class FriendMesh:
    """HTTP gossip mesh for bundle discovery and sharing between nodes."""

    def __init__(
        self,
        config_path: str | None = None,
        bundles_dir: pathlib.Path | None = None,
    ):
        self._config_path = config_path or _FRIENDS_CONFIG
        self._bundles_dir = bundles_dir or _BUNDLES_DIR
        self._config: Dict[str, Any] = {}
        self._load_config()

    # ── Config ─────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Load friends.yaml if it exists."""
        p = pathlib.Path(self._config_path)
        if p.exists():
            try:
                self._config = yaml.safe_load(p.read_text()) or {}
            except Exception as e:
                print(f"[Mesh] Failed to load {self._config_path}: {e}")
                self._config = {}
        else:
            self._config = {}

    @property
    def node_id(self) -> str:
        return self._config.get("node_id", "solo-node")

    @property
    def peers(self) -> List[Dict]:
        return self._config.get("peers", [])

    # ── Discovery ──────────────────────────────────────────────────────────────

    async def discover(self) -> Dict[str, Any]:
        """Contact all peers and return their bundle lists. No-op if MESH_ENABLED=false."""
        if not MESH_ENABLED:
            return {}

        results = {}
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in self.peers:
                url = peer.get("url", "").rstrip("/")
                try:
                    resp = await client.get(f"{url}/mesh/bundles")
                    if resp.status_code == 200:
                        results[url] = resp.json()
                        print(f"[Mesh] Discovered {len(results[url])} bundles from {url}")
                    else:
                        results[url] = []
                except Exception as e:
                    print(f"[Mesh] Peer {url} unreachable: {e}")
                    results[url] = []
        return results

    # ── Advertisement ──────────────────────────────────────────────────────────

    def advertise_bundles(self) -> List[Dict]:
        """Return list of local bundle manifests (no RAG, no secrets)."""
        bundles = []
        if not self._bundles_dir.exists():
            return bundles

        for bundle_dir in sorted(self._bundles_dir.iterdir()):
            manifest_path = bundle_dir / "manifest.yaml"
            if not manifest_path.exists():
                continue
            try:
                manifest = yaml.safe_load(manifest_path.read_text())
                signed = (bundle_dir / "signatures" / "bundle.sig").exists()
                # Only expose safe fields — never RAG, never secrets
                bundles.append({
                    "id": manifest.get("id", bundle_dir.name),
                    "name": manifest.get("name", ""),
                    "version": manifest.get("version", "1.0.0"),
                    "description": manifest.get("description", ""),
                    "capabilities": manifest.get("capabilities", []),
                    "temporal": manifest.get("temporal", {}),
                    "signed": signed,
                    "node_id": self.node_id,
                })
            except Exception as e:
                print(f"[Mesh] Skipped {bundle_dir.name}: {e}")
        return bundles

    def get_manifest(self, bundle_id: str) -> Optional[Dict]:
        """Return manifest dict for a specific bundle, or None."""
        bundle_dir = self._bundles_dir / bundle_id
        manifest_path = bundle_dir / "manifest.yaml"
        if not manifest_path.exists():
            return None
        try:
            return yaml.safe_load(manifest_path.read_text())
        except Exception:
            return None

    # ── Download ───────────────────────────────────────────────────────────────

    async def download_bundle(
        self,
        peer_url: str,
        bundle_id: str,
        crypto_manager: Any | None = None,
    ) -> bool:
        """Download bundle from peer (manifest + system.md only). Verify signature."""
        peer_url = peer_url.rstrip("/")
        target_dir = self._bundles_dir / bundle_id
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "prompts").mkdir(exist_ok=True)
        (target_dir / "signatures").mkdir(exist_ok=True)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1 — Download manifest.yaml
            try:
                resp = await client.get(f"{peer_url}/mesh/bundles/{bundle_id}/manifest")
                if resp.status_code != 200:
                    print(f"[Mesh] Failed to get manifest for {bundle_id}: {resp.status_code}")
                    return False
                manifest_data = resp.json()

                # Validate minimal manifest structure
                if not isinstance(manifest_data, dict) or "id" not in manifest_data:
                    print(f"[Mesh] Invalid manifest for {bundle_id}")
                    return False

                import yaml as _yaml
                (target_dir / "manifest.yaml").write_text(
                    _yaml.dump(manifest_data, default_flow_style=False, allow_unicode=True)
                )
            except Exception as e:
                print(f"[Mesh] Error downloading manifest {bundle_id}: {e}")
                return False

            # 2 — Download system.md (optional)
            try:
                resp2 = await client.get(f"{peer_url}/mesh/bundles/{bundle_id}/system_prompt")
                if resp2.status_code == 200:
                    (target_dir / "prompts" / "system.md").write_text(resp2.text)
            except Exception:
                pass  # system.md optional

        # 3 — Verify signature if crypto_manager provided
        if crypto_manager is not None:
            if not crypto_manager.verify_bundle(target_dir):
                print(f"[Mesh] Signature verification FAILED for {bundle_id} from {peer_url}")
                import shutil
                shutil.rmtree(target_dir, ignore_errors=True)
                return False

        print(f"[Mesh] Bundle {bundle_id} downloaded and installed from {peer_url}")
        return True

    # ── Status ─────────────────────────────────────────────────────────────────

    async def get_peers_status(self) -> List[Dict]:
        """Return online/offline status for each peer."""
        if not MESH_ENABLED:
            return [
                {
                    "url": p.get("url", ""),
                    "name": p.get("name", ""),
                    "online": False,
                    "bundle_count": 0,
                    "note": "MESH_ENABLED=false",
                }
                for p in self.peers
            ]

        results = []
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in self.peers:
                url = peer.get("url", "").rstrip("/")
                try:
                    resp = await client.get(f"{url}/mesh/status")
                    online = resp.status_code == 200
                    bundle_count = resp.json().get("bundle_count", 0) if online else 0
                except Exception:
                    online = False
                    bundle_count = 0
                results.append({
                    "url": url,
                    "name": peer.get("name", url),
                    "online": online,
                    "bundle_count": bundle_count,
                })
        return results

    def get_status(self) -> Dict[str, Any]:
        """Return mesh status summary."""
        bundle_count = sum(
            1 for d in self._bundles_dir.iterdir()
            if d.is_dir() and (d / "manifest.yaml").exists()
        ) if self._bundles_dir.exists() else 0

        return {
            "enabled": MESH_ENABLED,
            "node_id": self.node_id,
            "peer_count": len(self.peers),
            "bundle_count": bundle_count,
            "friends_config": self._config_path,
        }
