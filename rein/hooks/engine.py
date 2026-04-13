"""Hook execution engine.

Hooks are event-driven automation that intercept operations at lifecycle points.
Each hook can be either:
  - Command-based: runs a shell script, reads JSON from stdin, writes JSON to stdout
  - Prompt-based: uses an LLM to evaluate the hook condition

Hooks are fired in parallel and the first blocking result wins.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.config import HookConfig
from .types import HookEventType

logger = logging.getLogger(__name__)


@dataclass
class HookEvent:
    """Event fired through the hook system."""

    event_type: HookEventType
    session_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """Result of firing a hook event."""

    blocked: bool = False
    message: str = ""
    updated_input: dict[str, Any] | None = None
    system_messages: list[str] = field(default_factory=list)


class HookEngine:
    """Executes hooks in response to lifecycle events."""

    def __init__(self, settings: Any = None):
        self._hooks: list[HookConfig] = []
        if settings:
            self._hooks = list(settings.hooks)

    def register_hook(self, hook: HookConfig) -> None:
        self._hooks.append(hook)

    async def fire(self, event: HookEvent) -> HookResult:
        """Fire an event and collect results from all matching hooks.

        Hooks matching the event are run in parallel.
        If any hook blocks, the operation is blocked.
        """
        matching = self._get_matching_hooks(event)
        if not matching:
            return HookResult()

        # Run all matching hooks in parallel
        tasks = [self._execute_hook(hook, event) for hook in matching]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results: blocking takes priority
        merged = HookResult()
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Hook execution error: %s", r)
                continue
            if r.blocked:
                merged.blocked = True
                merged.message = r.message
            if r.updated_input:
                merged.updated_input = r.updated_input
            merged.system_messages.extend(r.system_messages)

        return merged

    def _get_matching_hooks(self, event: HookEvent) -> list[HookConfig]:
        """Filter hooks that match this event."""
        matching = []
        for hook in self._hooks:
            if hook.event != event.event_type.value:
                continue

            # Check matcher (tool name filter)
            if hook.matcher and event.event_type in (
                HookEventType.PRE_TOOL_USE,
                HookEventType.POST_TOOL_USE,
            ):
                tool_name = event.data.get("tool_name", "")
                if not re.match(hook.matcher, tool_name):
                    continue

            matching.append(hook)
        return matching

    async def _execute_hook(self, hook: HookConfig, event: HookEvent) -> HookResult:
        """Execute a single hook."""
        if hook.hook_type == "command":
            return await self._execute_command_hook(hook, event)
        elif hook.hook_type == "prompt":
            return await self._execute_prompt_hook(hook, event)
        else:
            logger.warning("Unknown hook type: %s", hook.hook_type)
            return HookResult()

    async def _execute_command_hook(
        self, hook: HookConfig, event: HookEvent
    ) -> HookResult:
        """Execute a command-based hook.

        Protocol:
          - Sends JSON to stdin with event context
          - Reads JSON from stdout with decision
          - Always expects exit code 0
        """
        if not hook.command:
            return HookResult()

        # Build input payload
        payload = {
            "hook_event_name": event.event_type.value,
            "session_id": event.session_id,
            **event.data,
        }

        try:
            proc = await asyncio.create_subprocess_shell(
                hook.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(json.dumps(payload).encode()),
                timeout=hook.timeout,
            )

            if stderr:
                logger.debug("Hook stderr: %s", stderr.decode(errors="replace"))

            if not stdout:
                return HookResult()

            # Parse JSON output
            try:
                output = json.loads(stdout.decode(errors="replace"))
            except json.JSONDecodeError:
                logger.warning("Hook returned non-JSON: %s", stdout[:200])
                return HookResult()

            return self._parse_hook_output(output, event.event_type)

        except asyncio.TimeoutError:
            logger.warning("Hook timed out after %ds: %s", hook.timeout, hook.command)
            return HookResult()
        except Exception as exc:
            logger.warning("Hook execution failed: %s", exc)
            return HookResult()

    async def _execute_prompt_hook(
        self, hook: HookConfig, event: HookEvent
    ) -> HookResult:
        """Execute a prompt-based hook (LLM evaluation).

        In a full implementation, this would call the LLM to evaluate
        the hook condition. For now, we log and allow.
        """
        logger.info(
            "Prompt hook for %s: %s", event.event_type.value, hook.prompt
        )
        # Prompt hooks would invoke the LLM here
        return HookResult(
            system_messages=[f"[Prompt hook] {hook.prompt}"] if hook.prompt else []
        )

    def _parse_hook_output(self, output: dict[str, Any], event_type: HookEventType) -> HookResult:
        """Parse hook output JSON into a HookResult."""
        result = HookResult()

        # System message
        sys_msg = output.get("systemMessage", "")
        if sys_msg:
            result.system_messages.append(sys_msg)

        # Check for blocking
        hook_specific = output.get("hookSpecificOutput", {})
        if hook_specific.get("permissionDecision") == "deny":
            result.blocked = True
            result.message = sys_msg or "Blocked by hook"

        # Stop event blocking
        if event_type == HookEventType.STOP:
            if output.get("decision") == "block":
                result.blocked = True
                result.message = output.get("reason", sys_msg or "Stop blocked by hook")

        # Updated input
        if "updatedInput" in hook_specific:
            result.updated_input = hook_specific["updatedInput"]

        return result
