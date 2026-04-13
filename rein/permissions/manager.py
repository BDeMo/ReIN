"""Permission manager — multi-layer access control for tools.

Permission decisions:
  - ALLOW: tool executes without user confirmation
  - DENY:  tool is blocked entirely
  - ASK:   user must approve before execution
"""

from __future__ import annotations

import fnmatch
import re
from enum import Enum
from typing import Any

from ..core.config import PermissionRule, Settings


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# Tools that are always safe (read-only)
ALWAYS_ALLOW = {"Read", "Grep", "Glob"}

# Tools that always require at least ASK in default mode
SENSITIVE_TOOLS = {"Bash", "Write", "Edit"}


class PermissionManager:
    """Evaluate permission rules for tool execution."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._rules = settings.permission_rules
        self._mode = settings.permission_mode

    def check(self, tool_name: str, tool_input: dict[str, Any] | None = None) -> PermissionDecision:
        """Check if a tool call is allowed.

        Resolution order:
          1. Explicit rules (first match wins)
          2. Mode-based defaults
        """
        # Check explicit rules first
        for rule in self._rules:
            if self._matches_tool(rule.tool, tool_name, tool_input):
                return PermissionDecision(rule.decision)

        # Mode-based defaults
        if self._mode == "dangerously_skip":
            return PermissionDecision.ALLOW

        if self._mode == "strict":
            if tool_name in ALWAYS_ALLOW:
                return PermissionDecision.ALLOW
            return PermissionDecision.ASK

        # Default mode
        if tool_name in ALWAYS_ALLOW:
            return PermissionDecision.ALLOW
        if tool_name in SENSITIVE_TOOLS:
            return PermissionDecision.ASK
        return PermissionDecision.ALLOW

    def _matches_tool(
        self, pattern: str, tool_name: str, tool_input: dict[str, Any] | None
    ) -> bool:
        """Check if a permission rule pattern matches a tool call.

        Patterns:
          - "Bash" — matches the Bash tool
          - "Bash(git:*)" — matches Bash when command starts with "git"
          - "Edit|Write" — matches Edit or Write
          - "mcp__*" — matches any MCP tool
        """
        # Handle OR patterns
        if "|" in pattern:
            return any(
                self._matches_tool(p.strip(), tool_name, tool_input)
                for p in pattern.split("|")
            )

        # Handle command-scoped patterns like Bash(git:*)
        match = re.match(r"^(\w+)\((.+)\)$", pattern)
        if match:
            base_tool = match.group(1)
            scope = match.group(2)

            if tool_name != base_tool:
                return False

            if base_tool == "Bash" and tool_input:
                command = tool_input.get("command", "")
                cmd_parts = command.strip().split()
                if not cmd_parts:
                    return False

                if ":" in scope:
                    prefix, suffix = scope.split(":", 1)
                    if suffix == "*":
                        return cmd_parts[0] == prefix
                    return cmd_parts[0] == prefix and (
                        len(cmd_parts) > 1 and cmd_parts[1] == suffix
                    )
                return fnmatch.fnmatch(command, scope)

            return True

        # Simple name or glob match
        return fnmatch.fnmatch(tool_name, pattern)
