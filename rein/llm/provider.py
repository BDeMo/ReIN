"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class StreamEvent:
    """A single event from the LLM stream.

    Types:
      - text_delta:    {"text": "..."}
      - tool_use:      {"id": "...", "name": "...", "input": {...}}
      - stop:          {"reason": "end_turn" | "tool_use" | "max_tokens"}
      - error:         {"message": "..."}
      - turn_complete: {"stop_reason": "..."}
      - tool_result:   {"tool_use_id": "...", "tool_name": "...", "result": "..."}
      - usage:         {"input_tokens": N, "output_tokens": N}
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract base for LLM providers (Anthropic, Bedrock, Vertex, etc.)."""

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion with tool use support.

        Yields StreamEvents as they arrive.
        """
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        """Non-streaming completion (for simple use cases)."""
        ...
