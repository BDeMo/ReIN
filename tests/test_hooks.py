"""Tests for hooks: engine and types."""

import asyncio

from rein.core.config import HookConfig
from rein.hooks.types import HookEventType
from rein.hooks.engine import HookEngine, HookEvent, HookResult


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestHookEventType:
    def test_all_types_exist(self):
        expected = [
            "PreToolUse", "PostToolUse", "Stop",
            "UserPromptSubmit", "SessionStart", "SessionEnd",
            "PreCompact", "Notification", "SubagentStop",
        ]
        for name in expected:
            assert HookEventType(name)

    def test_enum_values(self):
        assert HookEventType.PRE_TOOL_USE == "PreToolUse"
        assert HookEventType.STOP == "Stop"


class TestHookEngine:
    def test_no_hooks_returns_empty_result(self):
        engine = HookEngine()
        event = HookEvent(event_type=HookEventType.SESSION_START)
        result = run(engine.fire(event))
        assert not result.blocked
        assert result.message == ""

    def test_register_hook(self):
        engine = HookEngine()
        hook = HookConfig(
            event="PreToolUse",
            hook_type="command",
            command="echo test",
            matcher="Bash",
        )
        engine.register_hook(hook)
        assert len(engine._hooks) == 1

    def test_matching_by_event_type(self):
        engine = HookEngine()
        hook = HookConfig(event="SessionStart", hook_type="command", command="echo start")
        engine.register_hook(hook)

        # Should match
        matching = engine._get_matching_hooks(
            HookEvent(event_type=HookEventType.SESSION_START)
        )
        assert len(matching) == 1

        # Should not match
        matching = engine._get_matching_hooks(
            HookEvent(event_type=HookEventType.STOP)
        )
        assert len(matching) == 0

    def test_matcher_filters_tool_name(self):
        engine = HookEngine()
        hook = HookConfig(
            event="PreToolUse",
            hook_type="command",
            command="echo filtered",
            matcher="Bash",
        )
        engine.register_hook(hook)

        # Matches Bash
        matching = engine._get_matching_hooks(
            HookEvent(
                event_type=HookEventType.PRE_TOOL_USE,
                data={"tool_name": "Bash"},
            )
        )
        assert len(matching) == 1

        # Does not match Read
        matching = engine._get_matching_hooks(
            HookEvent(
                event_type=HookEventType.PRE_TOOL_USE,
                data={"tool_name": "Read"},
            )
        )
        assert len(matching) == 0

    def test_prompt_hook_returns_system_message(self):
        engine = HookEngine()
        hook = HookConfig(
            event="SessionStart",
            hook_type="prompt",
            prompt="Check safety",
        )
        engine.register_hook(hook)
        event = HookEvent(event_type=HookEventType.SESSION_START)
        result = run(engine.fire(event))
        assert not result.blocked
        assert len(result.system_messages) == 1
        assert "Check safety" in result.system_messages[0]

    def test_parse_hook_output_blocking(self):
        engine = HookEngine()
        output = {
            "systemMessage": "Blocked by policy",
            "hookSpecificOutput": {"permissionDecision": "deny"},
        }
        result = engine._parse_hook_output(output, HookEventType.PRE_TOOL_USE)
        assert result.blocked
        assert "Blocked by policy" in result.message

    def test_parse_hook_output_stop_block(self):
        engine = HookEngine()
        output = {
            "decision": "block",
            "reason": "Not allowed to stop",
        }
        result = engine._parse_hook_output(output, HookEventType.STOP)
        assert result.blocked
        assert "Not allowed to stop" in result.message

    def test_parse_hook_output_non_blocking(self):
        engine = HookEngine()
        output = {"systemMessage": "Info only"}
        result = engine._parse_hook_output(output, HookEventType.POST_TOOL_USE)
        assert not result.blocked
        assert "Info only" in result.system_messages
