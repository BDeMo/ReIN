"""Tests for plugin loader."""

import json
import tempfile
from pathlib import Path

from rein.core.config import Settings
from rein.plugins.loader import PluginLoader


class TestPluginLoader:
    def _make_plugin_dir(self, name="test-plugin", version="1.0.0"):
        base = Path(tempfile.mkdtemp())
        plugin_dir = base / name
        manifest_dir = plugin_dir / ".claude-plugin"
        manifest_dir.mkdir(parents=True)
        manifest = {"name": name, "version": version, "description": "A test plugin"}
        (manifest_dir / "plugin.json").write_text(json.dumps(manifest))
        return base, plugin_dir

    def test_discover_finds_plugin(self):
        base, _ = self._make_plugin_dir()
        settings = Settings(plugin_dirs=[str(base)])
        loader = PluginLoader(settings)
        plugins = loader.discover()
        assert len(plugins) == 1
        assert plugins[0].name == "test-plugin"
        assert plugins[0].version == "1.0.0"

    def test_discover_skips_blocked(self):
        base, _ = self._make_plugin_dir(name="blocked-plugin")
        settings = Settings(
            plugin_dirs=[str(base)],
            blocked_plugins=["blocked-plugin"],
        )
        loader = PluginLoader(settings)
        plugins = loader.discover()
        assert len(plugins) == 0

    def test_discover_empty_dir(self):
        base = Path(tempfile.mkdtemp())
        settings = Settings(plugin_dirs=[str(base)])
        loader = PluginLoader(settings)
        plugins = loader.discover()
        assert len(plugins) == 0

    def test_discover_no_manifest(self):
        base = Path(tempfile.mkdtemp())
        (base / "some-dir").mkdir()
        settings = Settings(plugin_dirs=[str(base)])
        loader = PluginLoader(settings)
        plugins = loader.discover()
        assert len(plugins) == 0

    def test_load_with_commands(self):
        base, plugin_dir = self._make_plugin_dir()
        cmds_dir = plugin_dir / "commands"
        cmds_dir.mkdir()
        (cmds_dir / "greet.md").write_text(
            "---\ndescription: Say hello\nallowed-tools: [Bash]\n---\nHello!"
        )
        settings = Settings(plugin_dirs=[str(base)])
        loader = PluginLoader(settings)
        plugins = loader.discover()
        assert len(plugins) == 1
        assert len(plugins[0].commands) == 1
        assert plugins[0].commands[0].name == "greet"
        assert "Hello!" in plugins[0].commands[0].content

    def test_load_with_hooks(self):
        base, plugin_dir = self._make_plugin_dir()
        hooks_dir = plugin_dir / "hooks"
        hooks_dir.mkdir()
        hooks_data = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo check"}],
                    }
                ]
            }
        }
        (hooks_dir / "hooks.json").write_text(json.dumps(hooks_data))
        settings = Settings(plugin_dirs=[str(base)])
        loader = PluginLoader(settings)
        plugins = loader.discover()
        assert len(plugins) == 1
        assert len(plugins[0].hooks) == 1
        assert plugins[0].hooks[0].event == "PreToolUse"

    def test_parse_frontmatter(self):
        content = "---\ndescription: Test\n---\nBody text here"
        fm, body = PluginLoader._parse_frontmatter(content)
        assert fm.get("description") == "Test"
        assert body == "Body text here"

    def test_parse_frontmatter_no_frontmatter(self):
        content = "Just plain text"
        fm, body = PluginLoader._parse_frontmatter(content)
        assert fm == {}
        assert body == "Just plain text"
