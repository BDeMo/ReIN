"""Tests for core: config, conversation."""

import json
import tempfile
from pathlib import Path

from rein.core.config import HookConfig, PermissionRule, Settings, SettingsManager
from rein.core.conversation import Conversation, Message


# --- Settings ---

class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.model == "claude-sonnet-4-20250514"
        assert s.max_tokens == 8192
        assert s.permission_mode == "default"
        assert s.hooks == []
        assert s.permission_rules == []

    def test_merge_override(self):
        base = Settings(model="base-model", max_tokens=1000)
        override = Settings(model="override-model")
        merged = base.merge(override)
        assert merged.model == "override-model"
        assert merged.max_tokens == 1000  # kept from base

    def test_merge_lists_concatenated(self):
        base = Settings(
            permission_rules=[PermissionRule(tool="Read", decision="allow")],
            hooks=[HookConfig(event="Stop", hook_type="command", command="echo hi")],
        )
        override = Settings(
            permission_rules=[PermissionRule(tool="Bash", decision="deny")],
            hooks=[HookConfig(event="SessionStart", hook_type="command", command="echo start")],
        )
        merged = base.merge(override)
        assert len(merged.permission_rules) == 2
        assert len(merged.hooks) == 2


class TestSettingsManager:
    def test_from_dict(self):
        mgr = SettingsManager(project_dir=tempfile.mkdtemp())
        data = {
            "model": "test-model",
            "maxTokens": 4096,
            "permissionMode": "strict",
            "permissions": [
                {"tool": "Bash", "decision": "deny"},
            ],
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo blocked"}],
                    }
                ]
            },
        }
        s = mgr._from_dict(data)
        assert s.model == "test-model"
        assert s.max_tokens == 4096
        assert s.permission_mode == "strict"
        assert len(s.permission_rules) == 1
        assert s.permission_rules[0].tool == "Bash"
        assert len(s.hooks) == 1
        assert s.hooks[0].event == "PreToolUse"
        assert s.hooks[0].matcher == "Bash"

    def test_parse_file_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            f.flush()
            mgr = SettingsManager()
            s = mgr._parse_file(Path(f.name))
            assert s.model == Settings().model  # returns defaults

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("CLAUDE_MODEL", "env-model")
        mgr = SettingsManager()
        s = mgr._from_env()
        assert s.api_key == "sk-test-key"
        assert s.model == "env-model"


# --- Conversation ---

class TestMessage:
    def test_to_api_format_string(self):
        msg = Message(role="user", content="hello")
        fmt = msg.to_api_format()
        assert fmt == {"role": "user", "content": "hello"}

    def test_to_api_format_list(self):
        blocks = [{"type": "text", "text": "hi"}]
        msg = Message(role="assistant", content=blocks)
        fmt = msg.to_api_format()
        assert fmt["content"] == blocks


class TestConversation:
    def test_add_messages(self):
        conv = Conversation()
        conv.add_user_message("hello")
        conv.add_assistant_message("hi there")
        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"
        assert conv.messages[1].role == "assistant"

    def test_add_tool_result(self):
        conv = Conversation()
        msg = conv.add_tool_result("tool-123", "result text", is_error=False)
        assert msg.role == "user"
        assert msg.tool_use_id == "tool-123"
        assert msg.content[0]["type"] == "tool_result"

    def test_get_api_messages(self):
        conv = Conversation()
        conv.add_user_message("test")
        msgs = conv.get_api_messages()
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "test"}

    def test_get_last_assistant_text_string(self):
        conv = Conversation()
        conv.add_user_message("q")
        conv.add_assistant_message("answer")
        assert conv.get_last_assistant_text() == "answer"

    def test_get_last_assistant_text_blocks(self):
        conv = Conversation()
        conv.add_assistant_message([
            {"type": "text", "text": "line1"},
            {"type": "text", "text": "line2"},
        ])
        assert conv.get_last_assistant_text() == "line1\nline2"

    def test_get_last_assistant_text_empty(self):
        conv = Conversation()
        assert conv.get_last_assistant_text() == ""

    def test_compact(self):
        conv = Conversation()
        for i in range(15):
            conv.add_user_message(f"msg {i}")
        summary = conv.compact(keep_last=5)
        assert "[Compacted conversation history]" in summary
        # 5 kept + 1 compacted summary = 6
        assert len(conv.messages) == 6

    def test_compact_no_op_if_short(self):
        conv = Conversation()
        conv.add_user_message("only one")
        result = conv.compact(keep_last=10)
        assert result == ""
        assert len(conv.messages) == 1

    def test_to_dict(self):
        conv = Conversation(session_id="test-session")
        conv.system_prompt = "You are helpful."
        conv.add_user_message("hi")
        d = conv.to_dict()
        assert d["session_id"] == "test-session"
        assert d["system_prompt"] == "You are helpful."
        assert len(d["messages"]) == 1

    def test_session_id_auto_generated(self):
        conv = Conversation()
        assert len(conv.session_id) == 16
