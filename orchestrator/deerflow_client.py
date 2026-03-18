"""BundleFabric Orchestrator — DeerFlow HTTP client with bundle system prompt injection."""
from __future__ import annotations
import os
import json
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator
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
    system_md_path = os.path.join(BUNDLES_DIR, bundle.id, "prompts", "system.md")
    system_md = ""
    try:
        if os.path.exists(system_md_path):
            with open(system_md_path, "r", encoding="utf-8") as f:
                system_md = f.read().strip()
    except Exception:
        pass

    if system_md:
        capabilities_line = ", ".join(bundle.capabilities[:8])
        return f"""{system_md}

---
**Bundle actif** : {bundle.name} (v{bundle.version})
**Capacités** : {capabilities_line}
**Score TPS** : {bundle.temporal.tps_score:.3f} ({bundle.temporal.status.value})
"""
    else:
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

    def _build_payload(
        self,
        bundle_id: str,
        intent: Intent,
        workflow_id: Optional[str],
        bundle: Optional[BundleManifest],
    ) -> tuple[list, str, dict]:
        messages = []
        system_prompt = ""
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
        return messages, system_prompt, payload

    async def execute_bundle(
        self,
        bundle_id: str,
        intent: Intent,
        workflow_id: Optional[str] = None,
        bundle: Optional[BundleManifest] = None,
    ) -> ExecutionResult:
        """Submit a bundle execution task to DeerFlow gateway."""
        _, system_prompt, payload = self._build_payload(bundle_id, intent, workflow_id, bundle)
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
                        metadata={"system_prompt_injected": bool(system_prompt),
                                  "bundle_name": bundle.name if bundle else None},
                    )
        except httpx.TimeoutException:
            return ExecutionResult(
                status="timeout", bundle_id=bundle_id, intent_goal=intent.goal, output="",
                error_message=f"DeerFlow request timed out after {DEERFLOW_TIMEOUT}s",
            )
        except httpx.ConnectError:
            return ExecutionResult(
                status="error", bundle_id=bundle_id, intent_goal=intent.goal, output="",
                error_message="Cannot connect to DeerFlow gateway — check sylvea_net connectivity",
            )
        except Exception as e:
            return ExecutionResult(
                status="error", bundle_id=bundle_id, intent_goal=intent.goal, output="",
                error_message=str(e),
            )

    async def execute_bundle_stream(
        self,
        bundle_id: str,
        intent: Intent,
        workflow_id: Optional[str] = None,
        bundle: Optional[BundleManifest] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream bundle execution as SSE events.
        Yields SSE-formatted strings: 'data: {...}\n\n'
        Always ends with 'event: done\ndata: {}\n\n' or 'event: error\ndata: {...}\n\n'
        """
        _, system_prompt, payload = self._build_payload(bundle_id, intent, workflow_id, bundle)

        # First event: metadata
        meta = {
            "type": "meta",
            "bundle_id": bundle_id,
            "bundle_name": bundle.name if bundle else bundle_id,
            "goal": intent.goal,
            "system_prompt_injected": bool(system_prompt),
        }
        yield f"data: {json.dumps(meta)}\n\n"

        try:
            async with httpx.AsyncClient(timeout=DEERFLOW_TIMEOUT + 60) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat/stream",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status_code not in (200, 201, 202):
                        error_body = await resp.aread()
                        yield f"event: error\ndata: {json.dumps({'message': f'DeerFlow HTTP {resp.status_code}', 'body': error_body.decode()[:200]})}\n\n"
                        return

                    # Try to stream chunks; if DeerFlow sends a single JSON blob, wrap it
                    full_text = ""
                    streamed_any = False
                    async for chunk in resp.aiter_text():
                        if chunk.strip():
                            streamed_any = True
                            # If chunk looks like SSE already (data: ...), forward it
                            if chunk.startswith("data:") or chunk.startswith("event:"):
                                yield chunk if chunk.endswith("\n\n") else chunk + "\n\n"
                            else:
                                # Treat as raw text token
                                full_text += chunk
                                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

                    if not streamed_any:
                        # DeerFlow returned nothing — yield empty done
                        pass

        except httpx.TimeoutException:
            yield f"event: error\ndata: {json.dumps({'message': f'DeerFlow timed out after {DEERFLOW_TIMEOUT}s'})}\n\n"
            return
        except httpx.ConnectError:
            yield f"event: error\ndata: {json.dumps({'message': 'Cannot connect to DeerFlow — check sylvea_net'})}\n\n"
            return
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            return

        yield "event: done\ndata: {}\n\n"
