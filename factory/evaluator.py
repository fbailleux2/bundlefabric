"""BundleFabric Factory — TPS score evaluator."""
from __future__ import annotations

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleStatus


class BundleEvaluator:
    """Calculates TPS scores and determines bundle lifecycle status."""

    def compute_obsolescence(
        self,
        bundle_manifest: dict,
        usage_count: int = 0,
        age_days: int = 0,
    ) -> float:
        """
        Compute obsolescence score: 0.0 = fresh, 1.0 = obsolete.
        Criteria: low freshness + low usage + old age.
        """
        temporal = bundle_manifest.get("temporal", {})
        freshness = float(temporal.get("freshness_score", 1.0))

        if freshness < 0.3 and usage_count < 5 and age_days > 30:
            return 0.9
        elif freshness < 0.5 and age_days > 60:
            return 0.6
        elif age_days > 90:
            return 0.4
        return max(0.0, round(1.0 - freshness, 2))

    def get_bundle_health(self, bundle_dir: "pathlib.Path") -> dict:
        """Return health report for a bundle: TPS, obsolescence, age, status, alerts."""
        import pathlib
        import time
        import yaml

        bundle_dir = pathlib.Path(bundle_dir)
        manifest_path = bundle_dir / "manifest.yaml"

        if not manifest_path.exists():
            return {"error": f"manifest.yaml not found in {bundle_dir}"}

        manifest = yaml.safe_load(manifest_path.read_text())
        temporal = manifest.get("temporal", {})

        freshness = float(temporal.get("freshness_score", 0.5))
        usage_freq = float(temporal.get("usage_frequency", 0.0))
        ecosystem = float(temporal.get("ecosystem_alignment", 0.5))
        usage_count = int(temporal.get("usage_count", 0))
        tps = round(freshness * 0.4 + usage_freq * 0.3 + ecosystem * 0.3, 3)

        # Age from manifest meta or file mtime
        created_at = manifest.get("meta", {}).get("created_at", "")
        if created_at:
            try:
                import datetime
                created_dt = datetime.datetime.strptime(created_at, "%Y-%m-%d")
                age_days = (datetime.datetime.now() - created_dt).days
            except Exception:
                age_days = int((time.time() - manifest_path.stat().st_mtime) / 86400)
        else:
            age_days = int((time.time() - manifest_path.stat().st_mtime) / 86400)

        obsolescence = self.compute_obsolescence(manifest, usage_count, age_days)
        status = temporal.get("status", "unknown")

        alerts = []
        if obsolescence >= 0.8:
            alerts.append("HIGH_OBSOLESCENCE: bundle may need rebuild")
        if tps < 0.3:
            alerts.append("LOW_TPS: bundle underperforming")
        if usage_count == 0 and age_days > 7:
            alerts.append("UNUSED: bundle never executed")
        signed = (bundle_dir / "signatures" / "bundle.sig").exists()
        if not signed:
            alerts.append("UNSIGNED: bundle not cryptographically signed")

        return {
            "id": manifest.get("id", bundle_dir.name),
            "tps": tps,
            "freshness": freshness,
            "usage_frequency": usage_freq,
            "usage_count": usage_count,
            "age_days": age_days,
            "obsolescence": obsolescence,
            "status": status,
            "signed": signed,
            "alerts": alerts,
        }


    # TPS thresholds → status
    STATUS_THRESHOLDS = {
        BundleStatus.active: 0.75,       # TPS >= 0.75
        BundleStatus.stable: 0.55,       # TPS >= 0.55
        BundleStatus.experimental: 0.40, # TPS >= 0.40 (also new bundles)
        BundleStatus.legacy: 0.25,       # TPS >= 0.25
        BundleStatus.archival: 0.0,      # TPS < 0.25
    }

    def calculate_tps(
        self,
        freshness: float,
        usage_frequency: float = 0.5,
        ecosystem_alignment: float = 0.5
    ) -> float:
        """
        TPS formula: freshness×0.4 + usage_frequency×0.3 + ecosystem_alignment×0.3
        Returns float in [0.0, 1.0].
        """
        tps = (
            max(0.0, min(1.0, freshness)) * 0.4
            + max(0.0, min(1.0, usage_frequency)) * 0.3
            + max(0.0, min(1.0, ecosystem_alignment)) * 0.3
        )
        return round(tps, 4)

    def get_status(self, tps_score: float) -> BundleStatus:
        """Determine lifecycle status from TPS score."""
        if tps_score >= self.STATUS_THRESHOLDS[BundleStatus.active]:
            return BundleStatus.active
        elif tps_score >= self.STATUS_THRESHOLDS[BundleStatus.stable]:
            return BundleStatus.stable
        elif tps_score >= self.STATUS_THRESHOLDS[BundleStatus.experimental]:
            return BundleStatus.experimental
        elif tps_score >= self.STATUS_THRESHOLDS[BundleStatus.legacy]:
            return BundleStatus.legacy
        else:
            return BundleStatus.archival

    def should_filter_archival(self, tps_score: float, threshold: float = 0.3) -> bool:
        """Return True if bundle should be filtered (archival + TPS below threshold)."""
        status = self.get_status(tps_score)
        return status == BundleStatus.archival and tps_score < threshold
