"""Anthropic Claude LLM provider with streaming and tool use."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import anthropic

from .provider import LLMProvider, StreamEvent

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider.

    Supports:
      - Streaming responses with Server-Sent Events
      - Tool use (function calling)
      - Multi-turn conversations
      - System prompts
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url

        self.client = anthropic.AsyncAnthropic(**kwargs)
        self.model = model

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a Claude response with tool use support.

        The Anthropic streaming API emits these event types:
          - message_start
          - content_block_start (text or tool_use)
          - content_block_delta (text_delta or input_json_delta)
          - content_block_stop
          - message_delta (stop_reason)
          - message_stop
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        # Track current tool use block for JSON assembly
        current_tool: dict[str, Any] | None = None
        current_tool_json = ""

        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool = {
                                "id": block.id,
                                "name": block.name,
                                "input": {},
                            }
                            current_tool_json = ""

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent(
                                type="text_delta", data={"text": delta.text}
                            )
                        elif delta.type == "input_json_delta":
                            current_tool_json += delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_tool is not None:
                            # Parse accumulated JSON
                            try:
                                current_tool["input"] = json.loads(
                                    current_tool_json
                                ) if current_tool_json else {}
                            except json.JSONDecodeError:
                                current_tool["input"] = {"_raw": current_tool_json}
                            yield StreamEvent(type="tool_use", data=current_tool)
                            current_tool = None
                            current_tool_json = ""

                    elif event.type == "message_delta":
                        stop_reason = getattr(event.delta, "stop_reason", "end_turn")
                        yield StreamEvent(
                            type="stop", data={"reason": stop_reason or "end_turn"}
                        )

                # Emit usage info
                final = await stream.get_final_message()
                yield StreamEvent(
                    type="usage",
                    data={
                        "input_tokens": final.usage.input_tokens,
                        "output_tokens": final.usage.output_tokens,
                    },
                )

        except anthropic.APIConnectionError as exc:
            yield StreamEvent(
                type="error", data={"message": f"Connection error: {exc}"}
            )
        except anthropic.RateLimitError as exc:
            yield StreamEvent(
                type="error", data={"message": f"Rate limited: {exc}"}
            )
        except anthropic.APIStatusError as exc:
            yield StreamEvent(
                type="error",
                data={"message": f"API error {exc.status_code}: {exc.message}"},
            )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        """Non-streaming completion."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self.client.messages.create(**kwargs)
            return {
                "content": [
                    block.model_dump() for block in response.content
                ],
                "stop_reason": response.stop_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }
        except anthropic.APIError as exc:
            return {"content": [], "stop_reason": "error", "error": str(exc)}
