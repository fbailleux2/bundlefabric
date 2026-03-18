"""BundleFabric Orchestrator — Intent extraction engine.

Dual-mode: keyword-based (instant, always works) + Ollama async enrichment (optional).
Claude Haiku enrichment available ONLY via Tailscale (X-Tailscale-Access: 1).
"""
from __future__ import annotations
import os
import re
import json
import asyncio
import pathlib
from typing import Optional, AsyncGenerator
import httpx

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.intent import Intent

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:18630")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-mini:4b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "15"))

ANTHROPIC_KEY_FILE = os.getenv("ANTHROPIC_KEY_FILE", "/app/secrets_vault/anthropic_key.txt")
CLAUDE_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT", "15"))
CLAUDE_MODEL = "claude-haiku-4-5"

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

# ── Anthropic key loading ────────────────────────────────────────────────────

_anthropic_api_key: Optional[str] = None
_claude_available: bool = False


def _load_anthropic_key() -> None:
    """Load Anthropic API key from file at module init. Never logs the key."""
    global _anthropic_api_key, _claude_available
    try:
        key_path = pathlib.Path(ANTHROPIC_KEY_FILE)
        if not key_path.exists():
            print(f"[Claude] WARNING: Key file not found at {ANTHROPIC_KEY_FILE} — claude_available=False")
            return
        key = key_path.read_text().strip()
        if not key or key == "PLACE_YOUR_ANTHROPIC_API_KEY_HERE" or len(key) < 20:
            print(f"[Claude] WARNING: Key file contains placeholder/empty value — claude_available=False")
            return
        _anthropic_api_key = key
        _claude_available = True
        print(f"[Claude] API key loaded from {ANTHROPIC_KEY_FILE} (len={len(key)}) — claude_available=True")
    except Exception as e:
        print(f"[Claude] WARNING: Failed to load key: {e} — claude_available=False")


_load_anthropic_key()


# ── Keyword extraction ───────────────────────────────────────────────────────

def extract_fast(text: str) -> Intent:
    """Keyword-based intent extraction — instant, always works, no LLM needed."""
    lower = text.lower()

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


# ── Ollama enrichment ────────────────────────────────────────────────────────

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
    except Exception:
        pass  # Graceful fallback to keyword-based intent

    return intent


# ── Claude Haiku enrichment (Tailscale-only) ─────────────────────────────────

async def enrich_with_claude_haiku(intent: Intent) -> Intent:
    """
    Claude Haiku enrichment — superior quality, ~300ms, confidence 0.95.
    Tailscale-only: caller must have verified X-Tailscale-Access: 1.
    Uses direct httpx POST to Anthropic REST API (no SDK, async-compatible).
    Key never logged — read once at module init from secrets_vault.
    """
    if not _claude_available or not _anthropic_api_key:
        return intent

    prompt = f"""Extract structured intent from this task request.

Request: "{intent.raw_text}"

Respond with ONLY this JSON (no markdown, no explanation):
{{
  "goal": "one sentence describing the goal",
  "domains": ["domain1", "domain2"],
  "keywords": ["kw1", "kw2", "kw3"],
  "complexity": "simple|medium|complex"
}}"""

    try:
        async with httpx.AsyncClient(timeout=CLAUDE_TIMEOUT) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": _anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["content"][0]["text"].strip()

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return Intent(
                    raw_text=intent.raw_text,
                    goal=parsed.get("goal", intent.goal),
                    domains=parsed.get("domains", intent.domains),
                    keywords=parsed.get("keywords", intent.keywords),
                    complexity=parsed.get("complexity", intent.complexity),
                    extraction_method="claude",
                    confidence=0.95,
                )
    except Exception:
        pass  # Graceful fallback — key never exposed in logs

    return intent



async def claude_execute_stream(
    intent_text: str,
    system_prompt: str,
    bundle_id: str,
    bundle_name: str,
) -> AsyncGenerator[str, None]:
    """
    Stream Claude Haiku bundle execution as SSE events.
    Yields SSE-formatted strings: data: .../event: done/event: error.
    Tailscale-only: caller must have verified X-Tailscale-Access: 1.
    """
    import json as _json

    if not _claude_available or not _anthropic_api_key:
        yield 'event: error\ndata: ' + _json.dumps({"message": "Claude not available"}) + '\n\n'
        return

    # First event: metadata
    meta = {
        "type": "meta",
        "bundle_id": bundle_id,
        "bundle_name": bundle_name,
        "goal": intent_text[:120],
        "system_prompt_injected": bool(system_prompt),
    }
    yield "data: " + _json.dumps(meta) + "\n\n"

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": _anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 2048,
                    "stream": True,
                    "system": system_prompt or "Tu es un assistant expert. Reponds de facon claire et precise.",
                    "messages": [{"role": "user", "content": intent_text}],
                },
            ) as resp:
                if resp.status_code != 200:
                    err_body = await resp.aread()
                    yield "event: error\ndata: " + _json.dumps({
                        "message": f"Claude HTTP {resp.status_code}",
                        "body": err_body.decode()[:200]
                    }) + "\n\n"
                    return

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            event = _json.loads(data_str)
                            etype = event.get("type", "")
                            if etype == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text = delta.get("text", "")
                                    if text:
                                        yield "data: " + _json.dumps({"type": "token", "content": text}) + "\n\n"
                        except Exception:
                            pass

    except httpx.TimeoutException:
        yield "event: error\ndata: " + _json.dumps({"message": "Claude stream timed out after 45s"}) + "\n\n"
        return
    except Exception as e:
        yield "event: error\ndata: " + _json.dumps({"message": str(e)}) + "\n\n"
        return

    yield "event: done\ndata: {}\n\n"

# ── Full extraction pipeline ─────────────────────────────────────────────────

async def extract(text: str, use_ollama: bool = True, use_claude: bool = False) -> Intent:
    """
    Full extraction pipeline:
    1. Always run keyword extraction (instant)
    2. Optionally enrich with Ollama async (best-effort, timeout)
    3. Optionally enrich with Claude Haiku (Tailscale-only, ~300ms)
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

    if use_claude and _claude_available:
        try:
            intent = await asyncio.wait_for(
                enrich_with_claude_haiku(intent),
                timeout=CLAUDE_TIMEOUT + 2
            )
        except asyncio.TimeoutError:
            pass  # Fallback to previous intent on timeout

    return intent


class IntentEngine:
    """Stateful wrapper for intent extraction."""

    def __init__(self, use_ollama: bool = True):
        self.use_ollama = use_ollama

    async def extract(self, text: str, use_ollama: bool = None, use_claude: bool = False) -> Intent:
        return await extract(
            text,
            use_ollama=use_ollama if use_ollama is not None else self.use_ollama,
            use_claude=use_claude,
        )

    def extract_sync(self, text: str) -> Intent:
        """Synchronous version for testing."""
        return extract_fast(text)
