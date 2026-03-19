"""BundleFabric Orchestrator — Bundle resolver and scorer.

Resolves natural language intent to the best-matching bundle using a
composite scoring formula:
    score = keyword_overlap × 0.5 + tps_score × 0.3 + recency × 0.2

Where:
  keyword_overlap — fraction of intent terms found in bundle metadata
  tps_score       — Temporal Pertinence Score from the bundle manifest
  recency         — 1.0 - (days_since_update / 365), capped at [0.1, 1.0]
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, "/opt/bundlefabric")
from models.bundle import BundleManifest
from models.intent import Intent, BundleMatch
from factory.loader import BundleLoader
from factory.evaluator import BundleEvaluator
from logging_config import get_logger

logger = get_logger("orchestrator.resolver")

BUNDLES_DIR = os.getenv("BUNDLES_DIR", "/opt/bundlefabric/bundles")


class BundleResolver:
    """Resolves the best bundles for a given intent using keyword + TPS scoring."""

    def __init__(self, loader: Optional[BundleLoader] = None):
        self.loader = loader or BundleLoader()
        self.evaluator = BundleEvaluator()

    def score_bundle(self, intent: Intent, bundle: BundleManifest) -> tuple[float, float, list]:
        """
        Score a bundle against an intent.
        Returns (composite_score, keyword_overlap, matched_keywords)
        Formula: keyword_overlap×0.5 + tps_score×0.3 + recency×0.2
        """
        # Keyword overlap: check intent keywords + domains against bundle capabilities + keywords
        intent_terms = set(
            [kw.lower() for kw in intent.keywords]
            + [d.lower() for d in intent.domains]
            + [w.lower() for w in intent.goal.split() if len(w) > 3]
        )
        bundle_terms = set(
            [kw.lower() for kw in bundle.keywords]
            + [c.lower() for c in bundle.capabilities]
            + [d.lower() for d in bundle.domains]
            + bundle.id.lower().replace("-", " ").split()
            + bundle.name.lower().split()
        )

        matched = intent_terms & bundle_terms
        keyword_overlap = len(matched) / max(len(intent_terms), 1)
        keyword_overlap = min(1.0, keyword_overlap)

        tps = bundle.temporal.tps_score

        # Recency: based on last_updated (default 0.5 if unknown)
        recency = 0.5
        if bundle.temporal.last_updated:
            try:
                updated = datetime.fromisoformat(bundle.temporal.last_updated)
                days_old = (datetime.utcnow() - updated).days
                recency = max(0.1, 1.0 - days_old / 365)
            except Exception:
                pass

        composite = keyword_overlap * 0.5 + tps * 0.3 + recency * 0.2
        return round(composite, 4), round(keyword_overlap, 4), list(matched)

    def find_matches(
        self,
        intent: Intent,
        top_k: int = 5,
        filter_archival: bool = True,
        min_score: float = 0.0,
    ) -> List[BundleMatch]:
        """
        Find best matching bundles for an intent.
        - Filters archival bundles with TPS < 0.3 if filter_archival=True
        - Returns top_k results sorted by score descending
        """
        all_bundles = self.loader.list_bundles()
        matches: List[BundleMatch] = []

        for bundle in all_bundles:
            tps = bundle.temporal.tps_score

            # Filter archival bundles with low TPS
            if filter_archival and self.evaluator.should_filter_archival(tps, threshold=0.3):
                continue

            composite, kw_overlap, matched_kws = self.score_bundle(intent, bundle)

            if composite >= min_score:
                matches.append(BundleMatch(
                    bundle_id=bundle.id,
                    bundle_name=bundle.name,
                    score=composite,
                    tps_score=tps,
                    keyword_overlap=kw_overlap,
                    matched_keywords=matched_kws,
                    explanation=f"Matched: {', '.join(matched_kws[:5]) or 'general'}",
                ))

        # Sort by composite score descending, return top-K results
        matches.sort(key=lambda m: m.score, reverse=True)
        top = matches[:top_k]
        logger.debug(
            "Resolved %d/%d bundle(s) — intent_domains=%s top=%s",
            len(top), len(all_bundles),
            intent.domains,
            [m.bundle_id for m in top[:3]],
        )
        return top
