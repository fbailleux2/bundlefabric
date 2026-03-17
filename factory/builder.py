"""BundleFabric Factory — Bundle scaffold builder."""
from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import yaml

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleManifest, TemporalScore, BundleStatus

BUNDLES_DIR = Path(os.getenv("BUNDLES_DIR", "/opt/bundlefabric/bundles"))


class BundleBuilder:
    """Creates new bundle directory structures with valid manifest.yaml."""

    def __init__(self, bundles_dir: Optional[Path] = None):
        self.bundles_dir = bundles_dir or BUNDLES_DIR

    def scaffold_bundle(
        self,
        bundle_id: str,
        name: str,
        description: str,
        capabilities: List[str],
        domains: List[str],
        keywords: List[str],
        version: str = "1.0.0",
        author: str = "bundlefabric",
        freshness_score: float = 0.8,
    ) -> BundleManifest:
        """
        Create bundle directory structure and generate manifest.yaml.
        Returns the created BundleManifest.
        """
        bundle_dir = self.bundles_dir / bundle_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Build temporal data
        temporal_data = {
            "status": "active",
            "freshness_score": freshness_score,
            "usage_frequency": 0.5,
            "ecosystem_alignment": 0.7,
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d"),
        }

        manifest_data = {
            "id": bundle_id,
            "version": version,
            "name": name,
            "description": description,
            "capabilities": capabilities,
            "domains": domains,
            "keywords": keywords,
            "temporal": temporal_data,
            "author": author,
            "license": "MIT",
        }

        # Write manifest.yaml
        manifest_path = bundle_dir / "manifest.yaml"
        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest_data, f, default_flow_style=False, allow_unicode=True)

        # Create stub files
        (bundle_dir / "README.md").write_text(
            f"# {name}\n\n{description}\n\n## Capabilities\n\n"
            + "\n".join(f"- {c}" for c in capabilities) + "\n"
        )
        (bundle_dir / "tools.yaml").write_text("# Bundle tools configuration\ntools: []\n")
        (bundle_dir / "prompts").mkdir(exist_ok=True)
        (bundle_dir / "prompts" / "system.md").write_text(
            f"# {name} — System Prompt\n\nYou are an expert in {', '.join(domains)}.\n"
        )

        return BundleManifest(**manifest_data)
