"""FastAPI server with WebSocket streaming for Claude Code runtime.

Endpoints:
  GET  /health              — health check
  GET  /api/tools           — list available tools
  GET  /api/settings        — current settings
  POST /api/chat            — non-streaming chat (simple)
  WS   /ws/chat             — WebSocket streaming chat (full harness)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.config import SettingsManager
from ..core.harness import Harness
from ..llm.anthropic_llm import AnthropicProvider

logger = logging.getLogger(__name__)

# ── Request/Response models ────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int] = {}


# ── App factory ────────────────────────────────────────────────────

def create_app(
    project_dir: str | None = None,
    local: bool = False,
    local_url: str | None = None,
    local_model: str | None = None,
    native_tools: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="ReIN",
        description="ReIN — an open-source agentic coding harness",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared state
    settings_mgr = SettingsManager(project_dir)
    harnesses: dict[str, Harness] = {}  # session_id -> Harness

    def _get_or_create_harness(session_id: str | None = None) -> Harness:
        settings = settings_mgr.settings
        if local:
            from ..llm.local_llm import LocalProvider
            import os
            url = local_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
            model = local_model or os.environ.get("LOCAL_LLM_MODEL", "qwen2.5-coder:7b")
            llm = LocalProvider(base_url=url, model=model, native_tool_use=native_tools or None)
        else:
            llm = AnthropicProvider(
                api_key=settings.api_key,
                base_url=settings.base_url,
                model=settings.model,
            )
        harness = Harness(llm=llm, settings_manager=settings_mgr, project_dir=project_dir)
        if session_id:
            harness.conversation.session_id = session_id
        harnesses[harness.conversation.session_id] = harness
        return harness

    # ── Routes ─────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok", "name": "ReIN", "version": "0.1.0"}

    @app.get("/api/tools")
    async def list_tools():
        harness = _get_or_create_harness()
        await harness.initialize()
        tools = harness.tool_registry.list_names()
        schemas = harness.tool_registry.get_schemas()
        await harness.shutdown()
        return {"tools": tools, "schemas": schemas}

    @app.get("/api/settings")
    async def get_settings():
        s = settings_mgr.settings
        return {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "permission_mode": s.permission_mode,
            "bash_sandbox": s.bash_sandbox,
            "plugins": [str(d) for d in s.plugin_dirs],
            "hooks_count": len(s.hooks),
            "permission_rules_count": len(s.permission_rules),
        }

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        """Non-streaming chat endpoint."""
        harness = _get_or_create_harness(req.session_id)
        await harness.initialize()

        if req.system_prompt:
            harness.set_system_prompt(req.system_prompt)

        full_text = ""
        tool_calls = []
        usage = {}

        async for event in harness.run_turn(req.message):
            if event.type == "text_delta":
                full_text += event.data.get("text", "")
            elif event.type == "tool_use":
                tool_calls.append(event.data)
            elif event.type == "usage":
                usage = event.data

        return ChatResponse(
            response=full_text,
            session_id=harness.conversation.session_id,
            tool_calls=tool_calls,
            usage=usage,
        )

    # ── WebSocket streaming ────────────────────────────────────────

    @app.websocket("/ws/chat")
    async def ws_chat(ws: WebSocket):
        """WebSocket endpoint for streaming chat.

        Protocol:
          Client sends: {"type": "message", "content": "...", "system_prompt": "..."}
          Server sends: {"type": "text_delta|tool_use|tool_result|stop|usage|error|turn_complete", "data": {...}}
        """
        await ws.accept()
        harness: Harness | None = None

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)

                if msg.get("type") == "message":
                    content = msg.get("content", "")
                    system_prompt = msg.get("system_prompt")

                    if harness is None:
                        harness = _get_or_create_harness(msg.get("session_id"))
                        await harness.initialize()
                        if system_prompt:
                            harness.set_system_prompt(system_prompt)

                    # Stream the response
                    async for event in harness.run_turn(content):
                        await ws.send_json({
                            "type": event.type,
                            "data": event.data,
                        })

                elif msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except json.JSONDecodeError as e:
            await ws.send_json({"type": "error", "data": {"message": f"Invalid JSON: {e}"}})
        except Exception as e:
            logger.exception("WebSocket error")
            try:
                await ws.send_json({"type": "error", "data": {"message": str(e)}})
            except Exception:
                pass
        finally:
            if harness:
                await harness.shutdown()

    return app
