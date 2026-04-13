"""Plugin discovery and loading.

Plugins are directories containing:
  .claude-plugin/plugin.json  — manifest (required)
  commands/                    — slash commands (*.md)
  agents/                      — autonomous subagents (*.md)
  skills/                      — knowledge modules
  hooks/hooks.json             — event automation
  .mcp.json                    — MCP server config
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import HookConfig, Settings

logger = logging.getLogger(__name__)


@dataclass
class CommandInfo:
    name: str
    description: str
    allowed_tools: list[str]
    content: str  # The markdown prompt


@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    path: Path
    hooks: list[HookConfig] = field(default_factory=list)
    commands: list[CommandInfo] = field(default_factory=list)
    mcp_servers: dict[str, Any] = field(default_factory=dict)


class PluginLoader:
    """Discover and load plugins."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._default_dirs = [
            Path.cwd() / "plugins",
            Path.home() / ".claude" / "plugins",
        ]

    def discover(self) -> list[PluginInfo]:
        """Discover all plugins from configured directories."""
        plugins: list[PluginInfo] = []
        search_dirs = [Path(d) for d in self.settings.plugin_dirs] + self._default_dirs

        for base_dir in search_dirs:
            if not base_dir.exists():
                continue
            for plugin_dir in base_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue
                manifest = plugin_dir / ".claude-plugin" / "plugin.json"
                if not manifest.exists():
                    continue

                # Skip blocked plugins
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue

                name = data.get("name", plugin_dir.name)
                if name in self.settings.blocked_plugins:
                    logger.info("Skipping blocked plugin: %s", name)
                    continue

                plugin = self._load_plugin(plugin_dir, data)
                if plugin:
                    plugins.append(plugin)

        logger.info("Discovered %d plugins", len(plugins))
        return plugins

    def _load_plugin(self, plugin_dir: Path, manifest: dict[str, Any]) -> PluginInfo | None:
        """Load a single plugin from its directory."""
        try:
            plugin = PluginInfo(
                name=manifest.get("name", plugin_dir.name),
                version=manifest.get("version", "0.0.0"),
                description=manifest.get("description", ""),
                path=plugin_dir,
            )

            # Load hooks
            hooks_file = plugin_dir / "hooks" / "hooks.json"
            if hooks_file.exists():
                plugin.hooks = self._load_hooks(hooks_file, plugin_dir)

            # Load commands
            commands_dir = plugin_dir / "commands"
            if commands_dir.exists():
                plugin.commands = self._load_commands(commands_dir)

            # Load MCP config
            mcp_file = plugin_dir / ".mcp.json"
            if mcp_file.exists():
                try:
                    plugin.mcp_servers = json.loads(mcp_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

            return plugin

        except Exception as exc:
            logger.warning("Failed to load plugin %s: %s", plugin_dir.name, exc)
            return None

    def _load_hooks(self, hooks_file: Path, plugin_dir: Path) -> list[HookConfig]:
        """Load hooks from hooks.json."""
        try:
            data = json.loads(hooks_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        hooks: list[HookConfig] = []
        for event_name, entries in data.get("hooks", {}).items():
            for entry in entries:
                matcher = entry.get("matcher")
                for h in entry.get("hooks", []):
                    command = h.get("command", "")
                    # Replace ${CLAUDE_PLUGIN_ROOT} with actual path
                    command = command.replace(
                        "${CLAUDE_PLUGIN_ROOT}", str(plugin_dir)
                    )
                    hooks.append(
                        HookConfig(
                            event=event_name,
                            hook_type=h.get("type", "command"),
                            command=command if h.get("type") == "command" else None,
                            prompt=h.get("prompt"),
                            matcher=matcher,
                            timeout=h.get("timeout", 60),
                        )
                    )
        return hooks

    def _load_commands(self, commands_dir: Path) -> list[CommandInfo]:
        """Load command definitions from markdown files."""
        commands: list[CommandInfo] = []
        for md_file in commands_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, body = self._parse_frontmatter(content)
                commands.append(
                    CommandInfo(
                        name=md_file.stem,
                        description=frontmatter.get("description", ""),
                        allowed_tools=frontmatter.get("allowed-tools", []),
                        content=body,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to load command %s: %s", md_file.name, exc)
        return commands

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
        """Parse YAML frontmatter from a markdown file."""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        try:
            import yaml
            frontmatter = yaml.safe_load(parts[1]) or {}
        except Exception:
            # Fallback: simple key-value parsing
            frontmatter = {}
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    frontmatter[key.strip()] = value.strip()

        return frontmatter, parts[2].strip()
