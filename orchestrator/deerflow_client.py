"""BundleFabric Orchestrator — DeerFlow HTTP client with bundle system prompt injection."""
from __future__ import annotations
import os
from typing import Optional, Dict, Any
import httpx

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.intent import Intent, ExecutionResult
from models.bundle import BundleManifest

DEERFLOW_URL = os.getenv("DEERFLOW_URL", "http://deer-flow-gateway:8001")
DEERFLOW_TIMEOUT = float(os.getenv("DEERFLOW_TIMEOUT", "30"))
BUNDLES_DIR = os.getenv("BUNDLES_DIR", "/app/bundles")


def _build_system_prompt(bundle: BundleManifest) -> str:
    """Build DeerFlow system prompt from bundle manifest + optional system.md file."""
    # Try to load optional prompts/system.md
    system_md_path = os.path.join(BUNDLES_DIR, bundle.id, "prompts", "system.md")
    system_md = ""
    try:
        if os.path.exists(system_md_path):
            with open(system_md_path, "r", encoding="utf-8") as f:
                system_md = f.read().strip()
    except Exception:
        pass

    if system_md:
        # Use the rich system.md content as primary prompt
        capabilities_line = ", ".join(bundle.capabilities[:8])
        return f"""{system_md}

---
**Bundle actif** : {bundle.name} (v{bundle.version})
**Capacités** : {capabilities_line}
**Score TPS** : {bundle.temporal.tps_score:.3f} ({bundle.temporal.status.value})
"""
    else:
        # Fallback: generate from manifest fields
        capabilities_line = "\n".join(f"- {c}" for c in bundle.capabilities[:10])
        return f"""Tu es {bundle.name}.

{bundle.description}

## Capacités
{capabilities_line}

Réponds en expert selon ces capacités. Sois précis, fournis du code prêt à l'emploi si applicable.
"""


class DeerFlowClient:
    """HTTP client for DeerFlow gateway API with bundle context injection."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or DEERFLOW_URL).rstrip("/")

    async def health_check(self) -> Dict[str, Any]:
        """Check DeerFlow gateway health status."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    return {"status": "online", "url": self.base_url, "data": resp.json()}
                else:
                    return {"status": "degraded", "url": self.base_url,
                            "http_status": resp.status_code}
        except httpx.ConnectError:
            return {"status": "offline", "url": self.base_url, "error": "Connection refused"}
        except Exception as e:
            return {"status": "error", "url": self.base_url, "error": str(e)}

    async def execute_bundle(
        self,
        bundle_id: str,
        intent: Intent,
        workflow_id: Optional[str] = None,
        bundle: Optional[BundleManifest] = None,
    ) -> ExecutionResult:
        """
        Submit a bundle execution task to DeerFlow gateway.
        Injects bundle system prompt as first message for context.
        """
        messages = []
        system_prompt = ""

        # Build and inject system prompt if bundle is provided
        if bundle is not None:
            system_prompt = _build_system_prompt(bundle)
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": intent.raw_text})

        payload = {
            "messages": messages,
            "bundle_id": bundle_id,
            "bundle_name": bundle.name if bundle else bundle_id,
            "workflow_id": workflow_id or bundle_id,
            "metadata": {
                "goal": intent.goal,
                "domains": intent.domains,
                "keywords": intent.keywords,
                "source": "bundlefabric",
                "has_system_prompt": bool(system_prompt),
                "bundle_name": bundle.name if bundle else None,
                "tps_score": bundle.temporal.tps_score if bundle else None,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=DEERFLOW_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat/stream",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201, 202):
                    data = resp.json() if resp.content else {}
                    return ExecutionResult(
                        status="success",
                        bundle_id=bundle_id,
                        intent_goal=intent.goal,
                        output=data.get("output", data.get("content", "Execution started")),
                        deerflow_thread_id=data.get("thread_id"),
                        deerflow_run_id=data.get("run_id"),
                        metadata={
                            "raw_response": data,
                            "system_prompt_injected": bool(system_prompt),
                            "bundle_name": bundle.name if bundle else None,
                        },
                    )
                else:
                    return ExecutionResult(
                        status="error",
                        bundle_id=bundle_id,
                        intent_goal=intent.goal,
                        output="",
                        error_message=f"DeerFlow returned HTTP {resp.status_code}",
                        metadata={"system_prompt_injected": bool(system_prompt), "bundle_name": bundle.name if bundle else None},
                    )
        except httpx.TimeoutException:
            return ExecutionResult(
                status="timeout",
                bundle_id=bundle_id,
                intent_goal=intent.goal,
                output="",
                error_message=f"DeerFlow request timed out after {DEERFLOW_TIMEOUT}s",
            )
        except httpx.ConnectError:
            return ExecutionResult(
                status="error",
                bundle_id=bundle_id,
                intent_goal=intent.goal,
                output="",
                error_message="Cannot connect to DeerFlow gateway — check sylvea_net connectivity",
            )
        except Exception as e:
            return ExecutionResult(
                status="error",
                bundle_id=bundle_id,
                intent_goal=intent.goal,
                output="",
                error_message=str(e),
            )
