"""BundleFabric Factory — TPS score evaluator."""
from __future__ import annotations

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleStatus


class BundleEvaluator:
    """Calculates TPS scores and determines bundle lifecycle status."""

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
