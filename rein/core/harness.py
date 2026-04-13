"""Harness — the core orchestrator of Claude Code runtime.

The harness coordinates:
  1. LLM calls (with streaming and tool use)
  2. Tool execution (with permission checks)
  3. Hook lifecycle (PreToolUse → Execute → PostToolUse)
  4. Conversation management
  5. Plugin loading
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from ..hooks.engine import HookEngine, HookEvent
from ..hooks.types import HookEventType
from ..llm.provider import LLMProvider, StreamEvent
from ..permissions.manager import PermissionDecision, PermissionManager
from ..plugins.loader import PluginLoader
from ..tools.registry import ToolRegistry
from .config import Settings, SettingsManager
from .conversation import Conversation

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """Result of a single agentic turn."""

    text: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "error"
    usage: dict[str, int]


class Harness:
    """Main runtime orchestrator."""

    def __init__(
        self,
        llm: LLMProvider,
        settings_manager: SettingsManager | None = None,
        project_dir: str | None = None,
    ):
        self.llm = llm
        self.settings_manager = settings_manager or SettingsManager(project_dir)
        self.settings = self.settings_manager.settings

        # Subsystems
        self.tool_registry = ToolRegistry()
        self.hook_engine = HookEngine(self.settings)
        self.permission_manager = PermissionManager(self.settings)
        self.plugin_loader = PluginLoader(self.settings)

        # State
        self.conversation = Conversation()
        self._running = False

    # ── Initialization ──────────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize all subsystems."""
        # Register built-in tools
        from ..tools.bash_tool import BashTool
        from ..tools.file_tools import EditTool, ReadTool, WriteTool
        from ..tools.search_tools import GlobTool, GrepTool

        self.tool_registry.register(ReadTool())
        self.tool_registry.register(WriteTool())
        self.tool_registry.register(EditTool())
        self.tool_registry.register(BashTool(sandbox=self.settings.bash_sandbox))
        self.tool_registry.register(GrepTool())
        self.tool_registry.register(GlobTool())

        # Load plugins and their hooks/tools
        plugins = self.plugin_loader.discover()
        for plugin in plugins:
            for hook_cfg in plugin.hooks:
                self.hook_engine.register_hook(hook_cfg)
            logger.info("Loaded plugin: %s", plugin.name)

        # Fire SessionStart hook
        await self.hook_engine.fire(
            HookEvent(
                event_type=HookEventType.SESSION_START,
                session_id=self.conversation.session_id,
            )
        )
        self._running = True

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        await self.hook_engine.fire(
            HookEvent(
                event_type=HookEventType.SESSION_END,
                session_id=self.conversation.session_id,
            )
        )
        self._running = False

    # ── Set system prompt ───────────────────────────────────────────

    def set_system_prompt(self, prompt: str) -> None:
        self.conversation.system_prompt = prompt

    # ── Main agentic loop ──────────────────────────────────────────

    async def run_turn(self, user_input: str) -> AsyncIterator[StreamEvent]:
        """Execute one full agentic turn with tool-use loop.

        Yields StreamEvents as they arrive from the LLM.
        Automatically handles tool calls and feeds results back.
        """
        # Fire UserPromptSubmit hook
        submit_result = await self.hook_engine.fire(
            HookEvent(
                event_type=HookEventType.USER_PROMPT_SUBMIT,
                session_id=self.conversation.session_id,
                data={"user_prompt": user_input},
            )
        )
        if submit_result.blocked:
            yield StreamEvent(type="error", data={"message": submit_result.message})
            return

        self.conversation.add_user_message(user_input)

        # Agentic loop: keep calling LLM until it stops using tools
        while True:
            # Prepare tool schemas for the API
            tool_schemas = self.tool_registry.get_schemas()

            # Call LLM with streaming
            assistant_content: list[dict[str, Any]] = []
            current_text = ""
            tool_calls: list[dict[str, Any]] = []
            stop_reason = "end_turn"

            async for event in self.llm.stream(
                messages=self.conversation.get_api_messages(),
                system=self.conversation.system_prompt,
                tools=tool_schemas,
                max_tokens=self.settings.max_tokens,
            ):
                yield event

                if event.type == "text_delta":
                    current_text += event.data.get("text", "")
                elif event.type == "tool_use":
                    tool_calls.append(event.data)
                elif event.type == "stop":
                    stop_reason = event.data.get("reason", "end_turn")

            # Build assistant content blocks
            if current_text:
                assistant_content.append({"type": "text", "text": current_text})
            for tc in tool_calls:
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["input"],
                    }
                )

            # Save assistant message
            if assistant_content:
                self.conversation.add_assistant_message(assistant_content)

            # If no tool calls, turn is done
            if not tool_calls:
                break

            # Execute each tool call through the harness pipeline
            for tc in tool_calls:
                result = await self._execute_tool_call(tc)
                yield StreamEvent(
                    type="tool_result",
                    data={
                        "tool_use_id": tc["id"],
                        "tool_name": tc["name"],
                        "result": result["content"],
                        "is_error": result.get("is_error", False),
                    },
                )
                self.conversation.add_tool_result(
                    tool_use_id=tc["id"],
                    content=result["content"],
                    is_error=result.get("is_error", False),
                )

        yield StreamEvent(type="turn_complete", data={"stop_reason": stop_reason})

    # ── Tool execution pipeline ────────────────────────────────────

    async def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """Execute a single tool call through the full harness pipeline.

        Pipeline:
          1. PreToolUse hook
          2. Permission check
          3. Tool execution
          4. PostToolUse hook
        """
        tool_name = tool_call["name"]
        tool_input = tool_call["input"]
        tool_use_id = tool_call["id"]

        # ── Step 1: PreToolUse hook ─────────────────────────────────
        pre_result = await self.hook_engine.fire(
            HookEvent(
                event_type=HookEventType.PRE_TOOL_USE,
                session_id=self.conversation.session_id,
                data={
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                },
            )
        )
        if pre_result.blocked:
            return {
                "content": f"[Blocked by hook] {pre_result.message}",
                "is_error": True,
            }
        # Hook may have modified the input
        if pre_result.updated_input:
            tool_input = pre_result.updated_input

        # ── Step 2: Permission check ───────────────────────────────
        decision = self.permission_manager.check(tool_name, tool_input)
        if decision == PermissionDecision.DENY:
            return {
                "content": f"[Permission denied] Tool '{tool_name}' is not allowed.",
                "is_error": True,
            }
        if decision == PermissionDecision.ASK:
            # In a real implementation, this would prompt the user
            # For now, we allow with a warning
            logger.warning("Tool '%s' requires user approval (auto-allowing)", tool_name)

        # ── Step 3: Execute tool ───────────────────────────────────
        tool = self.tool_registry.get(tool_name)
        if tool is None:
            return {
                "content": f"Unknown tool: {tool_name}",
                "is_error": True,
            }

        try:
            start = time.monotonic()
            result = await tool.execute(tool_input)
            elapsed = time.monotonic() - start
            logger.debug("Tool %s executed in %.2fs", tool_name, elapsed)
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            result = f"Error executing {tool_name}: {exc}"

        # ── Step 4: PostToolUse hook ───────────────────────────────
        post_result = await self.hook_engine.fire(
            HookEvent(
                event_type=HookEventType.POST_TOOL_USE,
                session_id=self.conversation.session_id,
                data={
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_output": result if isinstance(result, str) else str(result),
                },
            )
        )
        if post_result.message:
            result = f"{result}\n\n[Hook message] {post_result.message}"

        return {"content": result if isinstance(result, str) else str(result)}

    # ── Stop validation ────────────────────────────────────────────

    async def validate_stop(self, reason: str = "end_turn") -> bool:
        """Check if the agent is allowed to stop (Stop hook)."""
        result = await self.hook_engine.fire(
            HookEvent(
                event_type=HookEventType.STOP,
                session_id=self.conversation.session_id,
                data={"reason": reason},
            )
        )
        return not result.blocked
