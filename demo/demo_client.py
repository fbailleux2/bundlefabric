#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         BundleFabric — Python Client Demo                        ║
║  Demonstrates: auth → list bundles → intent → resolve → execute  ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    pip install requests
    export BF_API_KEY="your_api_key_here"
    python demo_client.py

Public instance:  https://api.bundlefabric.org
WebUI:            https://app.bundlefabric.org
"""

import logging
import os
import sys
import json
import time
from typing import Optional

try:
    import requests
except ImportError:
    print("❌ 'requests' library not installed. Run: pip install requests")
    sys.exit(1)

# ── Demo logger ───────────────────────────────────────────────────────────────
# Separate from the server-side logging_config — the demo is a standalone script.
# Run with --verbose / -v to enable DEBUG output.
_log = logging.getLogger("bundlefabric.demo")
_log.addHandler(logging.NullHandler())  # Silent unless configured by run_demo()


# ─────────────────────────────────────────────────────────────────────────────
# BundleFabric Client
# ─────────────────────────────────────────────────────────────────────────────

class BundleFabricClient:
    """Minimal Python client for the BundleFabric API."""

    def __init__(self, base_url: str = "https://api.bundlefabric.org", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> str:
        """Exchange API key for a JWT bearer token."""
        _log.debug("POST /auth/token")
        resp = self.session.post(
            f"{self.base_url}/auth/token",
            json={"api_key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("token") or data.get("access_token")
        if not self._token:
            raise ValueError(f"No token in auth response: {data}")
        self.session.headers["Authorization"] = f"Bearer {self._token}"
        _log.debug("JWT obtained — len=%d", len(self._token))
        return self._token

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        return self.session.get(f"{self.base_url}/health").json()

    def status(self) -> dict:
        return self.session.get(f"{self.base_url}/status").json()

    # ── Bundles ───────────────────────────────────────────────────────────────

    def list_bundles(self) -> list:
        resp = self.session.get(f"{self.base_url}/bundles")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("bundles", [])

    def get_bundle(self, bundle_id: str) -> dict:
        resp = self.session.get(f"{self.base_url}/bundles/{bundle_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Intent & Resolution ───────────────────────────────────────────────────

    def extract_intent(self, text: str) -> dict:
        """Extract keywords, domains and confidence from natural language."""
        resp = self.session.post(f"{self.base_url}/intent", json={"text": text})
        resp.raise_for_status()
        return resp.json()

    def resolve(self, text: str) -> dict:
        """Resolve natural language to best matching bundle (RAG + TPS)."""
        resp = self.session.post(f"{self.base_url}/resolve", json={"text": text})
        resp.raise_for_status()
        return resp.json()

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(self, bundle_id: str, query: str, timeout: int = 120) -> dict:
        """
        Execute a bundle with DeerFlow (LLM reasoning engine).

        ⚠️  Note: On CPU-only hardware with Ollama, this may take 30-120s.
              For production use, configure an OpenAI or Anthropic API key.
        """
        resp = self.session.post(
            f"{self.base_url}/execute",
            json={"bundle_id": bundle_id, "query": query},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Demo walkthrough
# ─────────────────────────────────────────────────────────────────────────────

def sep():
    print("─" * 56)

def step(n: int, total: int, title: str):
    print(f"\n\033[1;33m▶ {n}/{total} — {title}\033[0m")


def run_demo():
    import argparse
    parser = argparse.ArgumentParser(description="BundleFabric API demo")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    # Configure demo logger based on --verbose flag
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S"))
    _log.addHandler(handler)
    _log.setLevel(log_level)

    api_key = os.environ.get("BF_API_KEY", "")
    api_url = os.environ.get("BF_API_URL", "https://api.bundlefabric.org")

    if not api_key:
        print("❌ BF_API_KEY is not set.")
        print("   Set it with: export BF_API_KEY=your_api_key_here")
        sys.exit(1)

    client = BundleFabricClient(base_url=api_url, api_key=api_key)
    _log.debug("Demo starting — api_url=%s", api_url)

    sep()
    print("\033[1mBundleFabric Python Client Demo\033[0m")
    sep()

    # ── 1. Health ─────────────────────────────────────────────────────────────
    step(1, 5, "Health check")
    h = client.health()
    print(f"  Status  : {h.get('status', '?')}")
    print(f"  Version : {h.get('version', '?')}")

    # ── 2. Auth ───────────────────────────────────────────────────────────────
    step(2, 5, "Authentication (API key → JWT)")
    token = client.authenticate()
    print(f"  \033[32m✓ JWT obtained\033[0m ({len(token)} chars)")

    # ── 3. List bundles ───────────────────────────────────────────────────────
    step(3, 5, "List available bundles")
    bundles = client.list_bundles()
    print(f"  Found {len(bundles)} bundle(s):")
    for b in bundles:
        bid = b.get("id", "?")
        desc = b.get("description", "")[:60]
        tps = b.get("tps_score") or b.get("temporal", {}).get("usage_frequency", "?")
        tps_str = f"{tps:.3f}" if isinstance(tps, float) else str(tps)
        print(f"  • {bid:<30s}  TPS={tps_str}  — {desc}")

    # ── 4. Intent extraction ──────────────────────────────────────────────────
    step(4, 5, "Intent extraction")
    query = "How do I check nginx error logs on a Linux server?"
    print(f"  Query: \"{query}\"")

    intent = client.extract_intent(query)
    print(f"  Keywords  : {intent.get('keywords', [])}")
    print(f"  Domains   : {intent.get('domains', [])}")
    print(f"  Confidence: {intent.get('confidence', '?')}")

    # ── 5. Bundle resolution ──────────────────────────────────────────────────
    step(5, 5, "Bundle resolution (RAG + TPS scoring)")
    start = time.time()
    resolution = client.resolve(query)
    elapsed = time.time() - start

    bundle = resolution.get("bundle") or resolution.get("resolved_bundle") or resolution
    if isinstance(bundle, dict):
        bid = bundle.get("id") or bundle.get("bundle_id") or resolution.get("bundle_id", "?")
        score = bundle.get("tps_score") or bundle.get("score") or resolution.get("tps_score", "?")
    else:
        bid = resolution.get("bundle_id", "?")
        score = resolution.get("tps_score", "?")

    score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
    print(f"  \033[32m✓ Resolved in {elapsed:.1f}s\033[0m")
    print(f"    Bundle    : {bid}")
    print(f"    TPS score : {score_str}")
    print(f"    Method    : RAG vector search + TPS ranking")

    # ── Summary ───────────────────────────────────────────────────────────────
    sep()
    print("\033[1;32m✓ Demo complete!\033[0m")
    print()
    print("  Next steps:")
    print("  • WebUI   → https://app.bundlefabric.org")
    print("  • Docs    → https://bundlefabric.org/docs")
    print("  • Execute → client.execute('bundle-linux-ops', your_query)")
    print()
    print("  Note: DeerFlow execution uses a local LLM (Ollama).")
    print("  On CPU-only hardware, responses may take 30-120s.")
    print("  Configure OpenAI/Anthropic for instant responses.")
    sep()


if __name__ == "__main__":
    run_demo()
