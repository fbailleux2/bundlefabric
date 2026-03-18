"""BundleFabric — Meta-Agent: analyzes usage history, suggests new bundles via Claude Haiku."""
from __future__ import annotations

import json
import os
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import yaml

_DATA_DIR = pathlib.Path(os.getenv("HISTORY_DB", "/app/data/history.db")).parent
_SUGGESTIONS_FILE = _DATA_DIR / "meta_suggestions.json"
_ANTHROPIC_KEY_FILE = pathlib.Path(
    os.getenv("ANTHROPIC_KEY_FILE", "/app/secrets_vault/anthropic_key.txt")
)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")


def _get_api_key() -> Optional[str]:
    if _ANTHROPIC_KEY_FILE.exists():
        key = _ANTHROPIC_KEY_FILE.read_text().strip()
        return key if key and not key.startswith("#") else None
    return os.getenv("ANTHROPIC_API_KEY") or None


class MetaAgent:
    """Analyzes execution history to suggest and create new bundles."""

    def __init__(self, suggestions_file: pathlib.Path | None = None):
        self._suggestions_file = suggestions_file or _SUGGESTIONS_FILE

    # ── History analysis ──────────────────────────────────────────────────────

    async def analyze_history(self, db_path: str | pathlib.Path | None = None) -> List[Dict]:
        """
        Analyze execution history for unresolved intents (bundle_id IS NULL).
        Returns list of patterns: [{pattern, count, examples}]
        """
        if db_path is None:
            db_path = os.getenv("HISTORY_DB", "/app/data/history.db")

        try:
            import aiosqlite
            async with aiosqlite.connect(str(db_path)) as db:
                # Find intents that failed to resolve a bundle
                async with db.execute(
                    """
                    SELECT intent_text, COUNT(*) as cnt
                    FROM executions
                    WHERE (bundle_id IS NULL OR bundle_id = '')
                      AND intent_text IS NOT NULL
                      AND intent_text != ''
                    GROUP BY intent_text
                    HAVING cnt >= 2
                    ORDER BY cnt DESC
                    LIMIT 20
                    """
                ) as cursor:
                    rows = await cursor.fetchall()

                if not rows:
                    # Also check for intents even if bundle resolved — frequent themes
                    async with db.execute(
                        """
                        SELECT intent_text, COUNT(*) as cnt
                        FROM executions
                        WHERE intent_text IS NOT NULL
                        GROUP BY intent_text
                        HAVING cnt >= 3
                        ORDER BY cnt DESC
                        LIMIT 10
                        """
                    ) as cursor2:
                        rows = await cursor2.fetchall()

        except Exception as e:
            print(f"[MetaAgent] History analysis failed: {e}")
            return []

        patterns = []
        for intent_text, count in rows:
            patterns.append({
                "pattern": intent_text,
                "count": count,
                "examples": [intent_text],
            })

        print(f"[MetaAgent] Found {len(patterns)} usage patterns")
        return patterns

    # ── Suggestion generation ─────────────────────────────────────────────────

    async def suggest_bundle(self, pattern: Dict) -> Optional[Dict]:
        """Call Claude Haiku to generate a bundle manifest for the given pattern."""
        api_key = _get_api_key()
        if not api_key:
            print("[MetaAgent] No Claude API key available")
            return None

        prompt = f"""Tu es un expert en conception de bundles BundleFabric.

Un utilisateur répète cette intention sans trouver de bundle adapté :
"{pattern['pattern']}" (observé {pattern['count']} fois)

Génère un manifest YAML pour un nouveau bundle BundleFabric qui répondrait à ce besoin.

Format YAML attendu (réponds UNIQUEMENT avec le YAML, sans markdown) :
id: bundle-[kebab-case-id]
version: "1.0.0"
name: "[Nom lisible]"
description: "[Description en 1 phrase]"
capabilities:
  - [capability-1]
  - [capability-2]
meta:
  domain: [domaine]
  created_by: meta_agent
"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 512,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code != 200:
                    print(f"[MetaAgent] Claude error: {resp.status_code}")
                    return None

                content = resp.json()["content"][0]["text"].strip()
                # Strip markdown code fences if present
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

                manifest = yaml.safe_load(content)
                if not isinstance(manifest, dict) or "id" not in manifest:
                    print(f"[MetaAgent] Invalid manifest from Claude: {content[:100]}")
                    return None

                suggestion_id = str(uuid.uuid4())[:8]
                return {
                    "suggestion_id": suggestion_id,
                    "id": manifest.get("id", f"bundle-auto-{suggestion_id}"),
                    "name": manifest.get("name", "Auto-generated bundle"),
                    "description": manifest.get("description", ""),
                    "capabilities": manifest.get("capabilities", []),
                    "manifest_yaml": content,
                    "pattern": pattern["pattern"],
                    "pattern_count": pattern["count"],
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "status": "pending",
                }
        except Exception as e:
            print(f"[MetaAgent] Suggestion failed: {e}")
            return None

    # ── Suggestion CRUD ───────────────────────────────────────────────────────

    def load_suggestions(self) -> List[Dict]:
        """Load suggestions from file."""
        if self._suggestions_file.exists():
            try:
                return json.loads(self._suggestions_file.read_text())
            except Exception:
                pass
        return []

    def save_suggestions(self, suggestions: List[Dict]) -> None:
        """Save suggestions to file."""
        self._suggestions_file.parent.mkdir(parents=True, exist_ok=True)
        self._suggestions_file.write_text(
            json.dumps(suggestions, indent=2, ensure_ascii=False)
        )

    def add_suggestion(self, suggestion: Dict) -> str:
        """Add suggestion to store. Returns suggestion_id."""
        suggestions = self.load_suggestions()
        # Avoid duplicates by suggestion_id
        existing_ids = {s["suggestion_id"] for s in suggestions}
        sid = suggestion["suggestion_id"]
        if sid not in existing_ids:
            suggestions.append(suggestion)
            self.save_suggestions(suggestions)
        return sid

    def get_suggestions(self) -> List[Dict]:
        """Return all pending suggestions."""
        return [s for s in self.load_suggestions() if s.get("status") == "pending"]

    def create_from_suggestion(self, suggestion_id: str, builder: Any) -> Dict:
        """Create a bundle from a suggestion. Updates status to 'created'."""
        suggestions = self.load_suggestions()
        suggestion = next((s for s in suggestions if s["suggestion_id"] == suggestion_id), None)

        if not suggestion:
            raise ValueError(f"Suggestion '{suggestion_id}' not found")
        if suggestion.get("status") != "pending":
            raise ValueError(f"Suggestion '{suggestion_id}' already {suggestion['status']}")

        # Use builder to scaffold the bundle
        try:
            manifest = yaml.safe_load(suggestion["manifest_yaml"])
            bundle_id = manifest.get("id", f"bundle-auto-{suggestion_id}")

            result = builder.scaffold_bundle(
                bundle_id=bundle_id,
                name=manifest.get("name", bundle_id),
                description=manifest.get("description", ""),
                capabilities=manifest.get("capabilities", []),
                domains=[manifest.get("meta", {}).get("domain", "general")],
                keywords=manifest.get("capabilities", [])[:5],
            )

            # Update suggestion status
            for s in suggestions:
                if s["suggestion_id"] == suggestion_id:
                    s["status"] = "created"
                    s["created_bundle_id"] = bundle_id
            self.save_suggestions(suggestions)

            return {"bundle_id": bundle_id, "suggestion_id": suggestion_id, "result": result}

        except Exception as e:
            raise RuntimeError(f"Failed to create bundle from suggestion: {e}") from e
