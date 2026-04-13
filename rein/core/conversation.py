"""Conversation and message management."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str  # "user" | "assistant" | "system"
    content: Any  # str or list of content blocks
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_use_id: str | None = None  # for tool_result messages
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_api_format(self) -> dict[str, Any]:
        """Convert to Anthropic API message format."""
        msg: dict[str, Any] = {"role": self.role}
        if isinstance(self.content, str):
            msg["content"] = self.content
        else:
            msg["content"] = self.content
        return msg


class Conversation:
    """Manages a conversation's message history."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:16]
        self.messages: list[Message] = []
        self.system_prompt: str = ""
        self.created_at: float = time.time()

    def add_user_message(self, content: str) -> Message:
        msg = Message(role="user", content=content)
        self.messages.append(msg)
        return msg

    def add_assistant_message(self, content: Any) -> Message:
        msg = Message(role="assistant", content=content)
        self.messages.append(msg)
        return msg

    def add_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> Message:
        msg = Message(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
            tool_use_id=tool_use_id,
        )
        self.messages.append(msg)
        return msg

    def get_api_messages(self) -> list[dict[str, Any]]:
        """Get messages formatted for the Anthropic API."""
        return [m.to_api_format() for m in self.messages]

    def get_last_assistant_text(self) -> str:
        """Extract text from the last assistant message."""
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                if isinstance(msg.content, str):
                    return msg.content
                if isinstance(msg.content, list):
                    texts = [b["text"] for b in msg.content if b.get("type") == "text"]
                    return "\n".join(texts)
        return ""

    def compact(self, keep_last: int = 10) -> str:
        """Compact older messages into a summary, keeping recent ones.

        Returns the summary text for the compacted portion.
        """
        if len(self.messages) <= keep_last:
            return ""
        to_compact = self.messages[:-keep_last]
        self.messages = self.messages[-keep_last:]

        # Build a simple summary
        lines = []
        for msg in to_compact:
            role = msg.role
            if isinstance(msg.content, str):
                preview = msg.content[:200]
            else:
                preview = str(msg.content)[:200]
            lines.append(f"[{role}] {preview}")

        summary = "[Compacted conversation history]\n" + "\n".join(lines)
        # Prepend as a system-like user message
        self.messages.insert(0, Message(role="user", content=summary))
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                }
                for m in self.messages
            ],
            "system_prompt": self.system_prompt,
        }
