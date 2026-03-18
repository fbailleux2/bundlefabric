"""BundleFabric Orchestrator — DeerFlow LangGraph client (real integration).

Architecture:
  - deer-flow-gateway:8001  → FastAPI gateway (models, skills, memory — no chat)
  - deer-flow-langgraph:2024 → LangGraph server (threads + runs SSE streaming)

Flow:
  1. POST /threads           → create ephemeral thread
  2. POST /threads/{id}/runs/stream → stream SSE events
  3. Parse event: messages → token-by-token chunks
  4. Fallback: Claude Haiku if LangGraph timeout or unavailable
"""
from __future__ import annotations
import os
import json
import asyncio
import uuid
from typing import Optional, Dict, Any, AsyncGenerator
import httpx

import sys
sys.path.insert(0, "/opt/bundlefabric")
from models.intent import Intent, ExecutionResult
from models.bundle import BundleManifest

# ─── Configuration ────────────────────────────────────────────────────────────
DEERFLOW_URL = os.getenv("DEERFLOW_URL", "http://deer-flow-gateway:8001")
LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://deer-flow-langgraph:2024")
DEERFLOW_TIMEOUT = float(os.getenv("DEERFLOW_TIMEOUT", "120"))  # LLM inference is slow CPU-only
LANGGRAPH_FIRST_TOKEN_TIMEOUT = float(os.getenv("LANGGRAPH_FIRST_TOKEN_TIMEOUT", "90"))  # Ollama CPU: 60-120s typical
LANGGRAPH_ASSISTANT_ID = os.getenv("LANGGRAPH_ASSISTANT_ID", "bee7d354-5df5-5f26-a978-10ea053f620d")
BUNDLES_DIR = os.getenv("BUNDLES_DIR", "/app/bundles")

# ─── System prompt builder ────────────────────────────────────────────────────

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


# ─── SSE parser ───────────────────────────────────────────────────────────────

def _parse_langgraph_sse_chunk(raw: str) -> list[dict]:
    """Parse raw SSE text into list of {event, data} dicts."""
    events = []
    current_event = "message"
    current_data_lines = []

    for line in raw.split("\n"):
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line[5:].strip())
        elif line == "":
            if current_data_lines:
                data_str = "\n".join(current_data_lines)
                try:
                    data = json.loads(data_str) if data_str not in ("", "{}") else {}
                    events.append({"event": current_event, "data": data})
                except json.JSONDecodeError:
                    if data_str.strip():
                        events.append({"event": current_event, "data": {"raw": data_str}})
                current_event = "message"
                current_data_lines = []

    return events


def _extract_text_from_event(event_data) -> str:
    """Extract text content from a LangGraph messages event."""
    text = ""
    if isinstance(event_data, list):
        for msg in event_data:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    text += content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text += part.get("text", "")
    elif isinstance(event_data, dict):
        content = event_data.get("content", "")
        if isinstance(content, str):
            text += content
    return text


# ─── Main client ──────────────────────────────────────────────────────────────

class DeerFlowClient:
    """
    HTTP client for DeerFlow LangGraph server (deer-flow-langgraph:2024).

    Replaces the old client that called the non-existent /api/chat/stream.
    Uses LangGraph's threads/runs API for proper SSE streaming.
    """

    def __init__(self, base_url: Optional[str] = None):
        # base_url kept for backward compat (used by health_check for gateway)
        self.base_url = (base_url or DEERFLOW_URL).rstrip("/")
        self.langgraph_url = LANGGRAPH_URL.rstrip("/")
        self.assistant_id = LANGGRAPH_ASSISTANT_ID

    # ── Health check ─────────────────────────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """Check both gateway and LangGraph server health."""
        gateway_status: Dict[str, Any] = {}
        langgraph_status: Dict[str, Any] = {}

        # Gateway health
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    gateway_status = {"status": "online", "data": resp.json()}
                else:
                    gateway_status = {"status": "degraded", "http_status": resp.status_code}
        except httpx.ConnectError:
            gateway_status = {"status": "offline", "error": "Connection refused"}
        except Exception as e:
            gateway_status = {"status": "error", "error": str(e)}

        # LangGraph health
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.langgraph_url}/ok")
                if resp.status_code == 200:
                    langgraph_status = {"status": "online", "url": self.langgraph_url}
                else:
                    langgraph_status = {"status": "degraded", "http_status": resp.status_code}
        except httpx.ConnectError:
            langgraph_status = {"status": "offline", "error": "Connection refused"}
        except Exception as e:
            langgraph_status = {"status": "error", "error": str(e)}

        # Return combined status (keep backward-compat shape for /status endpoint)
        overall = "online" if langgraph_status.get("status") == "online" else langgraph_status.get("status", "error")
        return {
            "status": overall,
            "url": self.base_url,
            "data": {
                "status": "healthy",
                "service": "deer-flow-gateway",
                "langgraph": langgraph_status,
                "gateway": gateway_status,
            }
        }

    # ── Thread management ─────────────────────────────────────────────────────

    async def _create_thread(self, client: httpx.AsyncClient, bundle_id: str) -> str:
        """Create a LangGraph thread. Returns thread_id."""
        resp = await client.post(
            f"{self.langgraph_url}/threads",
            json={"metadata": {"source": "bundlefabric", "bundle_id": bundle_id}},
        )
        resp.raise_for_status()
        return resp.json()["thread_id"]

    # ── Execute (non-streaming) ───────────────────────────────────────────────

    def _build_langgraph_input(
        self,
        intent: Intent,
        bundle: Optional[BundleManifest],
    ) -> tuple[list, str]:
        """Build messages list and system_prompt for LangGraph input."""
        messages = []
        system_prompt = ""
        if bundle is not None:
            system_prompt = _build_system_prompt(bundle)
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "human", "content": intent.raw_text})
        return messages, system_prompt

    async def execute_bundle(
        self,
        bundle_id: str,
        intent: Intent,
        workflow_id: Optional[str] = None,
        bundle: Optional[BundleManifest] = None,
    ) -> ExecutionResult:
        """Execute bundle via LangGraph threads/runs/wait API (non-streaming)."""
        messages, system_prompt = self._build_langgraph_input(intent, bundle)

        try:
            async with httpx.AsyncClient(timeout=DEERFLOW_TIMEOUT) as client:
                # 1. Create thread
                thread_id = await self._create_thread(client, bundle_id)

                # 2. POST runs/wait (blocking until done)
                resp = await client.post(
                    f"{self.langgraph_url}/threads/{thread_id}/runs/wait",
                    json={
                        "assistant_id": self.assistant_id,
                        "input": {"messages": messages},
                        "context": {"thread_id": thread_id},
                        "config": {"recursion_limit": 10},
                    },
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    # LangGraph returns state with messages list
                    msgs = data.get("messages", [])
                    # Last AI message = final answer (DeerFlow/LangGraph message format variants)
                    output = ""
                    for msg in reversed(msgs):
                        if not isinstance(msg, dict):
                            continue
                        msg_type = msg.get("type", "")
                        msg_role = msg.get("role", "")
                        is_ai = (
                            msg_type in ("ai", "AIMessage", "AIMessageChunk")
                            or msg_role in ("assistant", "ai")
                        )
                        if is_ai:
                            raw_content = msg.get("content", "")
                            if isinstance(raw_content, str) and raw_content.strip():
                                output = raw_content
                                break
                            elif isinstance(raw_content, list):
                                # content block list format
                                parts = [
                                    p.get("text", "") for p in raw_content
                                    if isinstance(p, dict) and p.get("type") == "text"
                                ]
                                text = "".join(parts).strip()
                                if text:
                                    output = text
                                    break

                    return ExecutionResult(
                        status="success",
                        bundle_id=bundle_id,
                        intent_goal=intent.goal,
                        output=output or "DeerFlow execution complete.",
                        deerflow_thread_id=thread_id,
                        metadata={
                            "engine": "langgraph",
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
                        error_message=f"LangGraph returned HTTP {resp.status_code}",
                        metadata={"engine": "langgraph", "system_prompt_injected": bool(system_prompt)},
                    )

        except httpx.TimeoutException:
            return ExecutionResult(
                status="timeout", bundle_id=bundle_id, intent_goal=intent.goal, output="",
                error_message=f"LangGraph timed out after {DEERFLOW_TIMEOUT}s (Ollama CPU inference is slow)",
            )
        except httpx.ConnectError:
            return ExecutionResult(
                status="error", bundle_id=bundle_id, intent_goal=intent.goal, output="",
                error_message=f"Cannot connect to LangGraph at {self.langgraph_url}",
            )
        except Exception as e:
            return ExecutionResult(
                status="error", bundle_id=bundle_id, intent_goal=intent.goal, output="",
                error_message=str(e),
            )

    # ── Stream execution ──────────────────────────────────────────────────────

    async def execute_bundle_stream(
        self,
        bundle_id: str,
        intent: Intent,
        workflow_id: Optional[str] = None,
        bundle: Optional[BundleManifest] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream bundle execution via LangGraph threads/{id}/runs/stream SSE.

        Yields SSE strings: 'data: {...}\\n\\n' and 'event: done\\ndata: {}\\n\\n'

        LangGraph SSE event types:
          - event: metadata  → {run_id}
          - event: messages  → [{type, content}] — token chunks
          - event: end       → run finished
          - event: error     → run failed
        """
        messages, system_prompt = self._build_langgraph_input(intent, bundle)

        # First SSE event: metadata
        yield f"data: {json.dumps({'type': 'meta', 'bundle_id': bundle_id, 'bundle_name': bundle.name if bundle else bundle_id, 'goal': intent.goal, 'engine': 'langgraph', 'system_prompt_injected': bool(system_prompt)})}\n\n"

        thread_id = None
        try:
            timeout = httpx.Timeout(connect=10.0, read=DEERFLOW_TIMEOUT, write=10.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 1. Create thread
                try:
                    thread_id = await self._create_thread(client, bundle_id)
                    yield f"data: {json.dumps({'type': 'status', 'msg': f'Thread LangGraph créé: {thread_id[:8]}…'})}\n\n"
                except Exception as e:
                    yield f"event: error\ndata: {json.dumps({'message': f'Erreur création thread: {e}'})}\n\n"
                    return

                # 2. Stream run
                run_payload = {
                    "assistant_id": self.assistant_id,
                    "input": {"messages": messages},
                    "context": {"thread_id": thread_id},
                    "stream_mode": ["messages"],
                    "config": {"recursion_limit": 10},
                }

                async with client.stream(
                    "POST",
                    f"{self.langgraph_url}/threads/{thread_id}/runs/stream",
                    json=run_payload,
                    headers={"Accept": "text/event-stream"},
                ) as resp:
                    if resp.status_code not in (200, 201):
                        error_body = await resp.aread()
                        yield f"event: error\ndata: {json.dumps({'message': f'LangGraph HTTP {resp.status_code}: {error_body.decode()[:200]}'})}\n\n"
                        return

                    buf = ""
                    total_text = ""
                    heartbeat_count = 0
                    first_token_received = False
                    stream_start = asyncio.get_event_loop().time()

                    async for raw_chunk in resp.aiter_text():
                        if not raw_chunk.strip():
                            continue

                        # First-token timeout: if no real content in LANGGRAPH_FIRST_TOKEN_TIMEOUT seconds, abort
                        elapsed = asyncio.get_event_loop().time() - stream_start
                        if not first_token_received and elapsed > LANGGRAPH_FIRST_TOKEN_TIMEOUT:
                            yield f"event: error\ndata: {json.dumps({'message': f'LangGraph first-token timeout after {LANGGRAPH_FIRST_TOKEN_TIMEOUT:.0f}s (Ollama CPU too slow)'})}\n\n"
                            return

                        # Heartbeat detection
                        if raw_chunk.strip() == ": heartbeat":
                            heartbeat_count += 1
                            if heartbeat_count % 6 == 0:  # Every 6 heartbeats (~9s)
                                yield f"data: {json.dumps({'type': 'heartbeat', 'msg': f'LangGraph traite… ({elapsed:.0f}s)'})}\n\n"
                            continue

                        buf += raw_chunk
                        events = _parse_langgraph_sse_chunk(buf)
                        buf = ""  # Consumed

                        for ev in events:
                            event_type = ev.get("event", "message")
                            data = ev.get("data", {})

                            if event_type == "metadata":
                                run_id = data.get("run_id", "?")
                                yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"

                            elif event_type in ("messages", "message"):
                                text = _extract_text_from_event(data)
                                if text:
                                    first_token_received = True
                                    total_text += text
                                    yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

                            elif event_type == "end":
                                yield f"data: {json.dumps({'type': 'complete', 'total_length': len(total_text)})}\n\n"

                            elif event_type == "error":
                                if not isinstance(data, dict):
                                    err_msg = str(data) if data else "unknown error"
                                else:
                                    err_msg = data.get("message", data.get("error", str(data)))
                                yield f"event: error\ndata: {json.dumps({'message': f'LangGraph error: {err_msg}'})}\n\n"
                                return

        except httpx.TimeoutException:
            yield f"event: error\ndata: {json.dumps({'message': f'LangGraph timeout après {DEERFLOW_TIMEOUT}s — Ollama CPU lent'})}\n\n"
            return
        except httpx.ConnectError:
            yield f"event: error\ndata: {json.dumps({'message': f'Connexion LangGraph impossible: {self.langgraph_url}'})}\n\n"
            return
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            return

        yield "event: done\ndata: {}\n\n"
