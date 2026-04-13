"""Tests for permission manager."""

from rein.core.config import PermissionRule, Settings
from rein.permissions.manager import PermissionDecision, PermissionManager


class TestPermissionManager:
    def _make_manager(self, mode="default", rules=None):
        s = Settings(permission_mode=mode, permission_rules=rules or [])
        return PermissionManager(s)

    # --- Default mode ---

    def test_default_always_allow_read(self):
        pm = self._make_manager()
        assert pm.check("Read") == PermissionDecision.ALLOW
        assert pm.check("Grep") == PermissionDecision.ALLOW
        assert pm.check("Glob") == PermissionDecision.ALLOW

    def test_default_sensitive_tools_ask(self):
        pm = self._make_manager()
        assert pm.check("Bash") == PermissionDecision.ASK
        assert pm.check("Write") == PermissionDecision.ASK
        assert pm.check("Edit") == PermissionDecision.ASK

    def test_default_unknown_tool_allow(self):
        pm = self._make_manager()
        assert pm.check("SomeNewTool") == PermissionDecision.ALLOW

    # --- Strict mode ---

    def test_strict_read_allowed(self):
        pm = self._make_manager(mode="strict")
        assert pm.check("Read") == PermissionDecision.ALLOW

    def test_strict_bash_ask(self):
        pm = self._make_manager(mode="strict")
        assert pm.check("Bash") == PermissionDecision.ASK

    def test_strict_unknown_ask(self):
        pm = self._make_manager(mode="strict")
        assert pm.check("SomeNewTool") == PermissionDecision.ASK

    # --- Dangerously skip ---

    def test_skip_allows_everything(self):
        pm = self._make_manager(mode="dangerously_skip")
        assert pm.check("Bash") == PermissionDecision.ALLOW
        assert pm.check("Write") == PermissionDecision.ALLOW

    # --- Explicit rules ---

    def test_explicit_allow_overrides_default(self):
        rules = [PermissionRule(tool="Bash", decision="allow")]
        pm = self._make_manager(rules=rules)
        assert pm.check("Bash") == PermissionDecision.ALLOW

    def test_explicit_deny(self):
        rules = [PermissionRule(tool="Bash", decision="deny")]
        pm = self._make_manager(rules=rules)
        assert pm.check("Bash") == PermissionDecision.DENY

    def test_first_rule_wins(self):
        rules = [
            PermissionRule(tool="Bash", decision="deny"),
            PermissionRule(tool="Bash", decision="allow"),
        ]
        pm = self._make_manager(rules=rules)
        assert pm.check("Bash") == PermissionDecision.DENY

    # --- Pattern matching ---

    def test_or_pattern(self):
        rules = [PermissionRule(tool="Edit|Write", decision="deny")]
        pm = self._make_manager(rules=rules)
        assert pm.check("Edit") == PermissionDecision.DENY
        assert pm.check("Write") == PermissionDecision.DENY
        assert pm.check("Read") == PermissionDecision.ALLOW

    def test_glob_pattern(self):
        rules = [PermissionRule(tool="mcp__*", decision="allow")]
        pm = self._make_manager(rules=rules)
        assert pm.check("mcp__slack__send") == PermissionDecision.ALLOW

    def test_scoped_bash_pattern(self):
        rules = [PermissionRule(tool="Bash(git:*)", decision="allow")]
        pm = self._make_manager(rules=rules)
        assert pm.check("Bash", {"command": "git status"}) == PermissionDecision.ALLOW
        assert pm.check("Bash", {"command": "rm -rf ."}) == PermissionDecision.ASK  # falls through to default
