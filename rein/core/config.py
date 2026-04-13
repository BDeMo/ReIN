"""Hierarchical settings management.

Settings are loaded in priority order (higher overrides lower):
  1. managed-settings.json   (enterprise/admin)
  2. ~/.claude/settings.json (user global)
  3. .claude/settings.json   (project)
  4. Environment variables
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PermissionRule:
    tool: str  # tool name or pattern (e.g. "Bash(git:*)")
    decision: str  # "allow" | "deny" | "ask"


@dataclass
class HookConfig:
    event: str  # PreToolUse, PostToolUse, Stop, etc.
    hook_type: str  # "command" | "prompt"
    command: str | None = None  # shell command for command-type
    prompt: str | None = None  # LLM prompt for prompt-type
    matcher: str | None = None  # tool name regex filter
    timeout: int = 60


@dataclass
class Settings:
    # LLM
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    api_key: str | None = None
    base_url: str | None = None

    # Permissions
    permission_mode: str = "default"  # "default" | "strict" | "dangerously_skip"
    permission_rules: list[PermissionRule] = field(default_factory=list)

    # Hooks
    hooks: list[HookConfig] = field(default_factory=list)

    # Plugins
    plugin_dirs: list[str] = field(default_factory=list)
    blocked_plugins: list[str] = field(default_factory=list)

    # Sandbox
    bash_sandbox: bool = False

    # Enterprise
    allow_managed_hooks_only: bool = False
    allow_managed_permission_rules_only: bool = False
    disable_dangerously_skip_permissions: bool = False

    def merge(self, other: Settings) -> Settings:
        """Merge another settings on top of this one (other wins)."""
        import dataclasses

        merged = Settings()
        for f in dataclasses.fields(self):
            base_val = getattr(self, f.name)
            over_val = getattr(other, f.name)
            # Get default value
            if f.default is not dataclasses.MISSING:
                default_val = f.default
            elif f.default_factory is not dataclasses.MISSING:
                default_val = f.default_factory()
            else:
                default_val = None
            # Use override if it's not the default value
            if over_val != default_val:
                setattr(merged, f.name, over_val)
            else:
                setattr(merged, f.name, base_val)
        # Lists are concatenated, not replaced
        merged.permission_rules = self.permission_rules + other.permission_rules
        merged.hooks = self.hooks + other.hooks
        merged.plugin_dirs = self.plugin_dirs + other.plugin_dirs
        return merged


class SettingsManager:
    """Load and merge settings from the hierarchy."""

    def __init__(self, project_dir: str | None = None):
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._settings: Settings | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = self._load()
        return self._settings

    def reload(self) -> Settings:
        self._settings = None
        return self.settings

    def _load(self) -> Settings:
        layers: list[Settings] = []

        # Layer 1: managed-settings.json
        managed = self._find_managed_settings()
        if managed:
            layers.append(self._parse_file(managed))

        # Layer 2: ~/.claude/settings.json
        home_settings = Path.home() / ".claude" / "settings.json"
        if home_settings.exists():
            layers.append(self._parse_file(home_settings))

        # Layer 3: project .claude/settings.json
        project_settings = self.project_dir / ".claude" / "settings.json"
        if project_settings.exists():
            layers.append(self._parse_file(project_settings))

        # Layer 4: environment variables
        layers.append(self._from_env())

        # Merge all layers
        result = Settings()
        for layer in layers:
            result = result.merge(layer)

        return result

    def _find_managed_settings(self) -> Path | None:
        candidates = [
            Path.home() / ".claude" / "managed-settings.json",
            Path("/etc/claude/managed-settings.json"),
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _parse_file(self, path: Path) -> Settings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return Settings()
        return self._from_dict(data)

    def _from_dict(self, data: dict[str, Any]) -> Settings:
        s = Settings()
        s.model = data.get("model", s.model)
        s.max_tokens = data.get("maxTokens", s.max_tokens)
        s.api_key = data.get("apiKey", s.api_key)
        s.base_url = data.get("baseUrl", s.base_url)
        s.permission_mode = data.get("permissionMode", s.permission_mode)
        s.bash_sandbox = data.get("bashSandbox", s.bash_sandbox)
        s.allow_managed_hooks_only = data.get("allowManagedHooksOnly", False)
        s.allow_managed_permission_rules_only = data.get(
            "allowManagedPermissionRulesOnly", False
        )
        s.disable_dangerously_skip_permissions = data.get(
            "disableDangerouslySkipPermissions", False
        )

        # Parse permission rules
        for rule in data.get("permissions", []):
            if "tool" in rule and "decision" in rule:
                s.permission_rules.append(
                    PermissionRule(tool=rule["tool"], decision=rule["decision"])
                )

        # Parse hooks
        for event_name, hook_list in data.get("hooks", {}).items():
            for entry in hook_list:
                for h in entry.get("hooks", []):
                    s.hooks.append(
                        HookConfig(
                            event=event_name,
                            hook_type=h.get("type", "command"),
                            command=h.get("command"),
                            prompt=h.get("prompt"),
                            matcher=entry.get("matcher"),
                            timeout=h.get("timeout", 60),
                        )
                    )

        s.plugin_dirs = data.get("pluginDirs", [])
        s.blocked_plugins = data.get("blockedPlugins", [])
        return s

    def _from_env(self) -> Settings:
        s = Settings()
        s.api_key = os.environ.get("ANTHROPIC_API_KEY", s.api_key)
        s.base_url = os.environ.get("ANTHROPIC_BASE_URL", s.base_url)
        model = os.environ.get("CLAUDE_MODEL")
        if model:
            s.model = model
        return s
