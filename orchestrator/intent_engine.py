"""BundleFabric Orchestrator — Intent extraction engine.

Dual-mode: keyword-based (instant, always works) + Ollama async enrichment (optional).
"""
from __future__ import annotations
import os
import re
import asyncio
from typing import Optional
import httpx

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.intent import Intent

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:18630")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-mini:4b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "15"))

# Domain keyword mapping for fast extraction
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "linux": ["bash", "shell", "linux", "ubuntu", "debian", "chmod", "systemd",
              "apt", "ssh", "cron", "kernel", "process", "grep", "awk", "sed"],
    "docker": ["docker", "container", "compose", "dockerfile", "image", "registry",
               "kubernetes", "k8s", "pod", "helm"],
    "nginx": ["nginx", "proxy", "reverse proxy", "vhost", "ssl", "certificate",
              "letsencrypt", "certbot", "upstream"],
    "gtm": ["gtm", "google tag manager", "tag", "trigger", "datalayer", "data layer",
            "ga4", "google analytics", "analytics", "tracking"],
    "devops": ["ci", "cd", "pipeline", "deploy", "deployment", "git", "github",
               "gitlab", "actions", "terraform", "ansible"],
    "python": ["python", "fastapi", "django", "flask", "pip", "venv", "pydantic",
               "asyncio", "uvicorn"],
    "database": ["sql", "postgres", "postgresql", "mysql", "redis", "mongodb",
                 "supabase", "qdrant", "vector", "embedding"],
    "security": ["security", "vulnerability", "auth", "authentication", "jwt",
                 "oauth", "ssl", "tls", "firewall", "permission"],
    "woocommerce": ["woocommerce", "wordpress", "wp", "shop", "ecommerce", "order",
                    "product", "cart", "payment"],
}


def extract_fast(text: str) -> Intent:
    """Keyword-based intent extraction — instant, always works, no LLM needed."""
    lower = text.lower()
    words = set(re.findall(r"\b\w+\b", lower))

    # Extract domains from keyword matches
    matched_domains: list[str] = []
    matched_keywords: list[str] = []

    for domain, kws in DOMAIN_KEYWORDS.items():
        hits = [kw for kw in kws if kw in lower]
        if hits:
            matched_domains.append(domain)
            matched_keywords.extend(hits)

    # Simple goal: first sentence or first 80 chars
    goal = text.strip().split("\n")[0][:120].strip()
    if not goal:
        goal = text.strip()[:80]

    # Complexity heuristic
    word_count = len(text.split())
    if word_count < 10:
        complexity = "simple"
    elif word_count < 40:
        complexity = "medium"
    else:
        complexity = "complex"

    return Intent(
        raw_text=text,
        goal=goal,
        domains=matched_domains[:5],
        keywords=list(set(matched_keywords))[:10],
        complexity=complexity,
        extraction_method="keyword",
        confidence=0.7 if matched_domains else 0.4,
    )


async def enrich_with_ollama(intent: Intent) -> Intent:
    """Async Ollama enrichment — best-effort, falls back to original intent on failure."""
    prompt = f"""Analyze this task request and extract structured information.

Request: "{intent.raw_text}"

Respond with ONLY this JSON (no markdown, no explanation):
{{
  "goal": "one sentence describing the goal",
  "domains": ["domain1", "domain2"],
  "keywords": ["kw1", "kw2", "kw3"],
  "complexity": "simple|medium|complex"
}}"""

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 200},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "").strip()

            import json
            # Try to extract JSON from response
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return Intent(
                    raw_text=intent.raw_text,
                    goal=parsed.get("goal", intent.goal),
                    domains=parsed.get("domains", intent.domains),
                    keywords=parsed.get("keywords", intent.keywords),
                    complexity=parsed.get("complexity", intent.complexity),
                    extraction_method="ollama",
                    confidence=0.9,
                )
    except Exception as e:
        pass  # Graceful fallback to keyword-based intent

    return intent


async def extract(text: str, use_ollama: bool = True) -> Intent:
    """
    Full extraction pipeline:
    1. Always run keyword extraction (instant)
    2. Optionally enrich with Ollama async (best-effort, 15s timeout)
    """
    intent = extract_fast(text)

    if use_ollama:
        try:
            intent = await asyncio.wait_for(
                enrich_with_ollama(intent),
                timeout=OLLAMA_TIMEOUT + 2
            )
        except asyncio.TimeoutError:
            pass  # Return keyword-based intent on timeout

    return intent


class IntentEngine:
    """Stateful wrapper for intent extraction."""

    def __init__(self, use_ollama: bool = True):
        self.use_ollama = use_ollama

    async def extract(self, text: str, use_ollama: bool = None) -> Intent:
        return await extract(text, use_ollama=use_ollama if use_ollama is not None else self.use_ollama)

    def extract_sync(self, text: str) -> Intent:
        """Synchronous version for testing."""
        return extract_fast(text)
