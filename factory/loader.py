"""BundleFabric Factory — Bundle YAML loader and registry."""
from __future__ import annotations
import os
import shutil
import math
from pathlib import Path
from typing import List, Optional
import yaml

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleManifest, TemporalScore, BundleStatus

BUNDLES_DIR = Path(os.getenv("BUNDLES_DIR", "/opt/bundlefabric/bundles"))


class BundleNotFoundError(Exception):
    pass


class BundleLoader:
    """Loads and validates bundle manifests from YAML files."""

    def __init__(self, bundles_dir: Optional[Path] = None):
        self.bundles_dir = bundles_dir or BUNDLES_DIR

    def load_bundle(self, bundle_id: str) -> BundleManifest:
        """Load a bundle by ID from its manifest.yaml. Raises BundleNotFoundError if absent."""
        bundle_path = self.bundles_dir / bundle_id / "manifest.yaml"
        if not bundle_path.exists():
            raise BundleNotFoundError(
                f"Bundle '{bundle_id}' not found at {bundle_path}"
            )
        with open(bundle_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Ensure temporal sub-dict is properly nested
        if "temporal" not in data:
            data["temporal"] = {"freshness_score": 0.5}

        return BundleManifest(**data)

    def list_bundles(self) -> List[BundleManifest]:
        """List all valid bundles in the registry directory."""
        bundles: List[BundleManifest] = []
        if not self.bundles_dir.exists():
            return bundles
        for bundle_dir in sorted(self.bundles_dir.iterdir()):
            if bundle_dir.is_dir():
                try:
                    bundle = self.load_bundle(bundle_dir.name)
                    bundles.append(bundle)
                except BundleNotFoundError:
                    pass
                except Exception as e:
                    print(f"Warning: failed to load bundle {bundle_dir.name}: {e}")
        return bundles

    def list_bundle_ids(self) -> List[str]:
        """Return list of bundle IDs available."""
        if not self.bundles_dir.exists():
            return []
        return [
            d.name for d in sorted(self.bundles_dir.iterdir())
            if d.is_dir() and (d / "manifest.yaml").exists()
        ]

    def bundle_exists(self, bundle_id: str) -> bool:
        return (self.bundles_dir / bundle_id / "manifest.yaml").exists()

    def increment_usage(self, bundle_id: str) -> None:
        """Increment usage_count in manifest.yaml and recalculate usage_frequency."""
        bundle_path = self.bundles_dir / bundle_id / "manifest.yaml"
        if not bundle_path.exists():
            return
        try:
            with open(bundle_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            temporal = data.get("temporal", {})
            count = temporal.get("usage_count", 0) + 1
            temporal["usage_count"] = count
            # usage_frequency: logarithmic scale, caps at 1.0 after ~100 executions
            temporal["usage_frequency"] = round(min(1.0, math.log1p(count) / math.log1p(100)), 4)
            data["temporal"] = temporal
            with open(bundle_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"[Loader] increment_usage error for {bundle_id}: {e}")

    def update_bundle(self, bundle_id: str, updates: dict) -> BundleManifest:
        """Update allowed fields in manifest.yaml. Returns updated bundle."""
        bundle_path = self.bundles_dir / bundle_id / "manifest.yaml"
        if not bundle_path.exists():
            raise BundleNotFoundError(f"Bundle '{bundle_id}' not found")
        with open(bundle_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        allowed = {"name", "description", "capabilities", "domains", "keywords", "version"}
        for k, v in updates.items():
            if k in allowed and v is not None:
                data[k] = v
        with open(bundle_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        return self.load_bundle(bundle_id)

    def delete_bundle(self, bundle_id: str) -> None:
        """Remove bundle directory from filesystem."""
        bundle_dir = self.bundles_dir / bundle_id
        if not bundle_dir.exists():
            raise BundleNotFoundError(f"Bundle '{bundle_id}' not found")
        shutil.rmtree(bundle_dir)
