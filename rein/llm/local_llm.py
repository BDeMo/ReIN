"""Local LLM provider for offline operation.

Supports any OpenAI-compatible local server:
  - Ollama:      http://localhost:11434/v1
  - LM Studio:   http://localhost:1234/v1
  - llama.cpp:   http://localhost:8080/v1
  - vLLM:        http://localhost:8000/v1
  - LocalAI:     http://localhost:8080/v1

Two modes:
  1. Native tool use — for models that support OpenAI tool_call format
     (e.g. qwen2.5-coder, llama3.1, mistral-nemo with Ollama)
  2. Prompt-based tool use — injects tool schemas into the system prompt
     and parses JSON tool calls from the model's text output
     (works with ANY model, no native tool support needed)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

import httpx

from .provider import LLMProvider, StreamEvent

logger = logging.getLogger(__name__)

# ── Prompt-based tool use template ─────────────────────────────────

TOOL_SYSTEM_SUFFIX = """

## Available Tools

You have access to the following tools. To use a tool, respond with a JSON block:

```tool_call
{"name": "tool_name", "input": {"param": "value"}}
```

You may call multiple tools by including multiple ```tool_call blocks.
After each tool call, you will receive the result. Then continue your response.

Tools:
{tool_descriptions}
"""

TOOL_RESULT_PREFIX = """Tool result for `{name}`:
```
{result}
```
"""


class LocalProvider(LLMProvider):
    """LLM provider for local OpenAI-compatible servers.

    Args:
        base_url: Server URL (e.g. "http://localhost:11434/v1")
        model: Model name (e.g. "qwen2.5-coder:7b", "llama3.1:8b")
        native_tool_use: If True, use OpenAI tool_call format.
                         If False, use prompt-based tool calling.
                         If None (default), auto-detect.
        api_key: API key (most local servers accept any value or "ollama")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen2.5-coder:7b",
        native_tool_use: bool | None = None,
        api_key: str = "ollama",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._native_tool_use = native_tool_use
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))

    # ── Stream (main interface) ────────────────────────────────────

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from local LLM."""
        use_native = await self._should_use_native_tools(tools)

        if use_native and tools:
            async for event in self._stream_native(messages, system, tools, max_tokens):
                yield event
        else:
            async for event in self._stream_prompt_based(messages, system, tools, max_tokens):
                yield event

    # ── Native tool use mode ───────────────────────────────────────

    async def _stream_native(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        """Stream using OpenAI-compatible native tool calling."""
        oai_messages = self._to_openai_messages(messages, system)
        oai_tools = self._to_openai_tools(tools)

        body: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if oai_tools:
            body["tools"] = oai_tools

        current_tool_calls: dict[int, dict[str, Any]] = {}

        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=body,
                headers=self._headers(),
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    yield StreamEvent(type="error", data={"message": f"HTTP {resp.status_code}: {error_body.decode()}"})
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    finish = choice.get("finish_reason")

                    # Text content
                    if delta.get("content"):
                        yield StreamEvent(type="text_delta", data={"text": delta["content"]})

                    # Tool calls (streamed incrementally)
                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        if idx not in current_tool_calls:
                            current_tool_calls[idx] = {
                                "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": "",
                            }
                        entry = current_tool_calls[idx]
                        if tc.get("function", {}).get("name"):
                            entry["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            entry["arguments"] += tc["function"]["arguments"]

                    if finish:
                        # Emit completed tool calls
                        for entry in current_tool_calls.values():
                            try:
                                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                            except json.JSONDecodeError:
                                args = {"_raw": entry["arguments"]}
                            yield StreamEvent(
                                type="tool_use",
                                data={"id": entry["id"], "name": entry["name"], "input": args},
                            )
                        current_tool_calls.clear()

                        yield StreamEvent(
                            type="stop",
                            data={"reason": "tool_use" if finish == "tool_calls" else "end_turn"},
                        )

                # Usage (approximate — not all servers report this)
                usage = chunk.get("usage", {}) if 'chunk' in dir() else {}
                yield StreamEvent(
                    type="usage",
                    data={
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                    },
                )

        except httpx.ConnectError:
            yield StreamEvent(
                type="error",
                data={"message": f"Cannot connect to {self.base_url}. Is your local LLM server running?"},
            )
        except Exception as exc:
            yield StreamEvent(type="error", data={"message": f"Local LLM error: {exc}"})

    # ── Prompt-based tool use mode ─────────────────────────────────

    async def _stream_prompt_based(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        """Stream with tool schemas injected into the prompt.

        Parses ```tool_call JSON blocks from the model's text output.
        Works with ANY model — no native tool support needed.
        """
        # Inject tool descriptions into system prompt
        augmented_system = system
        if tools:
            tool_desc = self._format_tool_descriptions(tools)
            augmented_system += TOOL_SYSTEM_SUFFIX.format(tool_descriptions=tool_desc)

        # Convert messages — flatten tool_result into user text
        oai_messages = self._to_openai_messages_flat(messages, augmented_system)

        body = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }

        full_text = ""
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=body,
                headers=self._headers(),
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    yield StreamEvent(type="error", data={"message": f"HTTP {resp.status_code}: {error_body.decode()}"})
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})

                    if delta.get("content"):
                        text = delta["content"]
                        full_text += text
                        yield StreamEvent(type="text_delta", data={"text": text})

        except httpx.ConnectError:
            yield StreamEvent(
                type="error",
                data={"message": f"Cannot connect to {self.base_url}. Is your local LLM server running?"},
            )
            return
        except Exception as exc:
            yield StreamEvent(type="error", data={"message": f"Local LLM error: {exc}"})
            return

        # Parse tool calls from the accumulated text
        tool_calls = self._extract_tool_calls(full_text)
        if tool_calls:
            for tc in tool_calls:
                yield StreamEvent(type="tool_use", data=tc)
            yield StreamEvent(type="stop", data={"reason": "tool_use"})
        else:
            yield StreamEvent(type="stop", data={"reason": "end_turn"})

        yield StreamEvent(type="usage", data={"input_tokens": 0, "output_tokens": 0})

    # ── Non-streaming complete ─────────────────────────────────────

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        """Non-streaming completion."""
        content_blocks = []
        stop_reason = "end_turn"

        async for event in self.stream(messages, system, tools, max_tokens):
            if event.type == "text_delta":
                if not content_blocks or content_blocks[-1]["type"] != "text":
                    content_blocks.append({"type": "text", "text": ""})
                content_blocks[-1]["text"] += event.data.get("text", "")
            elif event.type == "tool_use":
                content_blocks.append({
                    "type": "tool_use",
                    "id": event.data["id"],
                    "name": event.data["name"],
                    "input": event.data["input"],
                })
            elif event.type == "stop":
                stop_reason = event.data.get("reason", "end_turn")

        return {"content": content_blocks, "stop_reason": stop_reason}

    # ── Auto-detect native tool support ────────────────────────────

    async def _should_use_native_tools(self, tools: list | None) -> bool:
        if self._native_tool_use is not None:
            return self._native_tool_use
        if not tools:
            return False

        # Models known to support native tool use
        native_models = [
            "qwen", "llama3", "mistral", "mixtral", "command-r",
            "firefunction", "hermes", "functionary", "gorilla",
        ]
        model_lower = self.model.lower()
        for m in native_models:
            if m in model_lower:
                self._native_tool_use = True
                return True

        # Default to prompt-based (safer, works everywhere)
        self._native_tool_use = False
        return False

    # ── Message format conversion ──────────────────────────────────

    def _to_openai_messages(
        self, messages: list[dict[str, Any]], system: str
    ) -> list[dict[str, Any]]:
        """Convert Anthropic-format messages to OpenAI format."""
        oai: list[dict[str, Any]] = []
        if system:
            oai.append({"role": "system", "content": system})

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                oai.append({"role": role, "content": content})
            elif isinstance(content, list):
                # Handle Anthropic content blocks
                parts = []
                tool_results = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            # Assistant's tool call
                            oai.append({"role": "assistant", "content": None, "tool_calls": [{
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            }]})
                        elif block.get("type") == "tool_result":
                            tool_results.append({
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": block.get("content", ""),
                            })

                if parts:
                    oai.append({"role": role, "content": "\n".join(parts)})
                oai.extend(tool_results)

        return oai

    def _to_openai_messages_flat(
        self, messages: list[dict[str, Any]], system: str
    ) -> list[dict[str, Any]]:
        """Convert to OpenAI format but flatten tool calls/results into text.

        Used for prompt-based mode where the model doesn't understand tool_call objects.
        """
        oai: list[dict[str, Any]] = []
        if system:
            oai.append({"role": "system", "content": system})

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                oai.append({"role": role, "content": content})
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            parts.append(
                                f'```tool_call\n{json.dumps({"name": block["name"], "input": block["input"]})}\n```'
                            )
                        elif block.get("type") == "tool_result":
                            result_text = block.get("content", "")
                            parts.append(
                                TOOL_RESULT_PREFIX.format(
                                    name="tool", result=result_text[:2000]
                                )
                            )
                if parts:
                    oai.append({"role": role, "content": "\n".join(parts)})

        return oai

    def _to_openai_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic tool schema to OpenAI tool format."""
        oai_tools = []
        for tool in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return oai_tools

    # ── Tool call extraction (prompt-based mode) ───────────────────

    @staticmethod
    def _extract_tool_calls(text: str) -> list[dict[str, Any]]:
        """Extract ```tool_call JSON blocks from model text output."""
        pattern = r"```tool_call\s*\n(.*?)\n```"
        matches = re.findall(pattern, text, re.DOTALL)

        calls = []
        for match in matches:
            try:
                data = json.loads(match.strip())
                calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "name": data.get("name", ""),
                    "input": data.get("input", {}),
                })
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool call JSON: %s", match[:100])
        return calls

    @staticmethod
    def _format_tool_descriptions(tools: list[dict[str, Any]]) -> str:
        """Format tool schemas for injection into the system prompt."""
        lines = []
        for tool in tools:
            name = tool["name"]
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            props = schema.get("properties", {})
            required = schema.get("required", [])

            lines.append(f"### {name}")
            lines.append(f"{desc}")
            lines.append("Parameters:")
            for pname, pinfo in props.items():
                req = " (required)" if pname in required else ""
                pdesc = pinfo.get("description", "")
                ptype = pinfo.get("type", "string")
                lines.append(f"  - {pname}: {ptype}{req} — {pdesc}")
            lines.append("")
        return "\n".join(lines)

    # ── Helpers ────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    async def close(self):
        await self._client.aclose()
