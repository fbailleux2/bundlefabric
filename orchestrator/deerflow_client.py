"""BundleFabric Orchestrator — DeerFlow HTTP client."""
from __future__ import annotations
import os
from typing import Optional, Dict, Any
import httpx

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.intent import Intent, ExecutionResult

DEERFLOW_URL = os.getenv("DEERFLOW_URL", "http://deer-flow-gateway:2026")
DEERFLOW_TIMEOUT = float(os.getenv("DEERFLOW_TIMEOUT", "30"))


class DeerFlowClient:
    """HTTP client for DeerFlow gateway API."""

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
    ) -> ExecutionResult:
        """
        Submit a bundle execution task to DeerFlow gateway.
        DeerFlow LangGraph API: POST /api/chat/stream or /api/runs
        """
        payload = {
            "messages": [{"role": "user", "content": intent.raw_text}],
            "bundle_id": bundle_id,
            "workflow_id": workflow_id or bundle_id,
            "metadata": {
                "goal": intent.goal,
                "domains": intent.domains,
                "keywords": intent.keywords,
                "source": "bundlefabric",
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
                        metadata={"raw_response": data},
                    )
                else:
                    return ExecutionResult(
                        status="error",
                        bundle_id=bundle_id,
                        intent_goal=intent.goal,
                        output="",
                        error_message=f"DeerFlow returned HTTP {resp.status_code}",
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
