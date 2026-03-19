"""BundleFabric Factory — Bundle YAML loader and registry.

Responsibilities:
  - Load / validate bundle manifests from YAML files on disk
  - CRUD: create, update, delete bundles
  - TPS maintenance: increment usage_count + recalculate usage_frequency
"""
from __future__ import annotations

import math
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

import yaml

sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleManifest, TemporalScore, BundleStatus
from logging_config import get_logger

logger = get_logger("factory.loader")

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

        # Ensure temporal sub-dict is present — older manifests may omit it
        if "temporal" not in data:
            data["temporal"] = {"freshness_score": 0.5}
            logger.debug("Bundle '%s' missing temporal section — using defaults", bundle_id)

        bundle = BundleManifest(**data)
        logger.debug("Bundle loaded — id=%s tps=%.3f", bundle_id, bundle.temporal.tps_score)
        return bundle

    def list_bundles(self) -> List[BundleManifest]:
        """List all valid bundles in the registry directory."""
        bundles: List[BundleManifest] = []
        if not self.bundles_dir.exists():
            logger.warning("Bundles directory does not exist: %s", self.bundles_dir)
            return bundles
        for bundle_dir in sorted(self.bundles_dir.iterdir()):
            if bundle_dir.is_dir():
                try:
                    bundle = self.load_bundle(bundle_dir.name)
                    bundles.append(bundle)
                except BundleNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning("Failed to load bundle '%s': %s", bundle_dir.name, exc)
        logger.debug("Listed %d bundle(s) from %s", len(bundles), self.bundles_dir)
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
            logger.debug(
                "Usage incremented — bundle=%s count=%d freq=%.4f",
                bundle_id, count, temporal["usage_frequency"],
            )
        except Exception as exc:
            logger.error("increment_usage failed for '%s': %s", bundle_id, exc)

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
        logger.info("Bundle updated — id=%s fields=%s", bundle_id, list(updates.keys()))
        return self.load_bundle(bundle_id)

    def delete_bundle(self, bundle_id: str) -> None:
        """Remove bundle directory from filesystem."""
        bundle_dir = self.bundles_dir / bundle_id
        if not bundle_dir.exists():
            raise BundleNotFoundError(f"Bundle '{bundle_id}' not found")
        shutil.rmtree(bundle_dir)
        logger.info("Bundle deleted — id=%s", bundle_id)
