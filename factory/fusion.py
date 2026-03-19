"""BundleFabric — Bundle fusion (merge multiple bundles into one composite)."""
from __future__ import annotations

import os
import pathlib
import sys
sys.path.insert(0, "/opt/bundlefabric")
from logging_config import get_logger

logger = get_logger("factory.fusion")
import secrets
import time
from typing import Any, Dict, List

import yaml

_BUNDLES_DIR = pathlib.Path(os.getenv("BUNDLES_DIR", "/app/bundles"))


class BundleFusion:
    """Creates composite bundles by merging capabilities and prompts."""

    def __init__(self, bundles_dir: pathlib.Path | None = None):
        self.bundles_dir = bundles_dir or _BUNDLES_DIR

    def _load_bundle(self, bundle_id: str) -> tuple[Dict[str, Any], str]:
        """Load manifest + system.md for a bundle. Returns (manifest, system_prompt)."""
        bundle_dir = self.bundles_dir / bundle_id
        manifest_path = bundle_dir / "manifest.yaml"
        if not manifest_path.exists():
            raise ValueError(f"Bundle '{bundle_id}' not found at {bundle_dir}")
        manifest = yaml.safe_load(manifest_path.read_text())
        system_path = bundle_dir / "prompts" / "system.md"
        system_prompt = system_path.read_text() if system_path.exists() else f"# {bundle_id}\nNo system prompt."
        return manifest, system_prompt

    def merge(self, bundle_ids: List[str]) -> Dict[str, Any]:
        """
        Merge 2+ bundles into a composite fusion bundle.
        Returns dict with {id, path, sources, manifest}.
        """
        if len(bundle_ids) < 2:
            raise ValueError("Fusion requires at least 2 bundle IDs")

        # Deduplicate while preserving order
        seen = set()
        unique_ids = [bid for bid in bundle_ids if not (bid in seen or seen.add(bid))]

        # Load all source bundles
        sources = []
        for bid in unique_ids:
            manifest, system_prompt = self._load_bundle(bid)
            sources.append({"id": bid, "manifest": manifest, "system_prompt": system_prompt})

        # Build fusion ID
        id_slug = "-".join(sorted(unique_ids[:2]))[:40]
        token = secrets.token_hex(4)
        fusion_id = f"fusion-{id_slug}-{token}"

        # Merge capabilities (union, deduplicated)
        all_caps: List[str] = []
        for s in sources:
            for cap in s["manifest"].get("capabilities", []):
                if cap not in all_caps:
                    all_caps.append(cap)

        # Merge system prompts with clear separators
        system_sections = []
        for s in sources:
            system_sections.append(f"# [{s['id']}]\n\n{s['system_prompt'].strip()}")
        merged_system = "\n\n---\n\n".join(system_sections)

        # Compute averaged freshness + ecosystem
        freshness_scores = [
            float(s["manifest"].get("temporal", {}).get("freshness_score", 0.5))
            for s in sources
        ]
        ecosystem_scores = [
            float(s["manifest"].get("temporal", {}).get("ecosystem_alignment", 0.5))
            for s in sources
        ]
        avg_freshness = round(sum(freshness_scores) / len(freshness_scores), 3)
        avg_ecosystem = round(sum(ecosystem_scores) / len(ecosystem_scores), 3)

        # Build fusion manifest
        fusion_manifest = {
            "id": fusion_id,
            "version": "1.0.0",
            "name": f"Fusion: {' + '.join(s['manifest'].get('name', s['id']) for s in sources)}",
            "description": (
                f"Composite bundle fusing: "
                + ", ".join(s["manifest"].get("name", s["id"]) for s in sources)
            ),
            "capabilities": all_caps,
            "fusion_sources": unique_ids,
            "temporal": {
                "status": "experimental",
                "freshness_score": avg_freshness,
                "usage_frequency": 0.0,
                "ecosystem_alignment": avg_ecosystem,
                "usage_count": 0,
            },
            "meta": {
                "created_by": "fusion_engine",
                "created_at": time.strftime("%Y-%m-%d"),
            },
        }

        # Write fusion bundle directory
        fusion_dir = self.bundles_dir / fusion_id
        fusion_dir.mkdir(parents=True, exist_ok=True)
        (fusion_dir / "prompts").mkdir(exist_ok=True)

        (fusion_dir / "manifest.yaml").write_text(
            yaml.dump(fusion_manifest, default_flow_style=False, allow_unicode=True)
        )
        (fusion_dir / "prompts" / "system.md").write_text(merged_system)

        logger.info("Fusion bundle created — id=%s sources=%s", fusion_id, unique_ids)
        return {
            "id": fusion_id,
            "path": str(fusion_dir),
            "sources": unique_ids,
            "manifest": fusion_manifest,
        }
