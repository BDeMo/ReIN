"""Bash tool with command filtering and security checks."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from .registry import BaseTool

logger = logging.getLogger(__name__)

# Commands that are always blocked
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",         # rm -rf /
    r"rm\s+-rf\s+/\*",           # rm -rf /*
    r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",  # fork bomb
    r"mkfs\.",                     # format filesystem
    r"dd\s+if=.*of=/dev/",        # dd to device
    r">\s*/dev/sd[a-z]",          # redirect to disk
]


class BashTool(BaseTool):
    """Execute bash commands with security filtering.

    Supports command patterns for permission scoping:
      - Bash(git:*) — only allow git subcommands
      - Bash(npm:*) — only allow npm subcommands
      - Bash(*) — allow all commands
    """

    def __init__(self, sandbox: bool = False, allowed_patterns: list[str] | None = None):
        self._sandbox = sandbox
        self._allowed_patterns = allowed_patterns  # e.g. ["git:*", "npm:*"]

    @property
    def name(self) -> str:
        return "Bash"

    @property
    def description(self) -> str:
        return (
            "Execute a bash command and return its output. "
            "The working directory persists between commands."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120, max: 600).",
                    "default": 120,
                    "maximum": 600,
                },
            },
            "required": ["command"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        command = params["command"]
        timeout = min(params.get("timeout", 120), 600)

        # Security check: blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command):
                return f"Error: Command blocked for safety: {command}"

        # Allowed pattern filtering
        if self._allowed_patterns:
            if not self._matches_allowed(command):
                return (
                    f"Error: Command not in allowed patterns. "
                    f"Allowed: {self._allowed_patterns}"
                )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Use shell on Windows, bash on Unix
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                output_parts.append(stderr.decode("utf-8", errors="replace"))

            output = "\n".join(output_parts)

            # Truncate very long output
            max_len = 100_000
            if len(output) > max_len:
                output = output[:max_len] + f"\n... (truncated, {len(output)} total chars)"

            if proc.returncode != 0:
                output = f"Exit code: {proc.returncode}\n{output}"

            return output or "(no output)"

        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"

    def _matches_allowed(self, command: str) -> bool:
        """Check if command matches any allowed pattern."""
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False
        base_cmd = cmd_parts[0]

        for pattern in self._allowed_patterns:  # type: ignore[union-attr]
            if pattern == "*":
                return True
            if ":" in pattern:
                prefix, suffix = pattern.split(":", 1)
                if base_cmd == prefix and suffix == "*":
                    return True
                if base_cmd == prefix and len(cmd_parts) > 1:
                    sub = cmd_parts[1]
                    if suffix == "*" or sub == suffix:
                        return True
        return False
