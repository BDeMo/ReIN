"""Hook event types and data structures."""

from __future__ import annotations

from enum import Enum


class HookEventType(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PRE_COMPACT = "PreCompact"
    NOTIFICATION = "Notification"
    SUBAGENT_STOP = "SubagentStop"
