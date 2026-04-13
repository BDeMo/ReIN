"""Tests for tools: registry, file tools, bash security, search tools."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

from rein.tools.registry import BaseTool, ToolRegistry
from rein.tools.file_tools import ReadTool, WriteTool, EditTool
from rein.tools.bash_tool import BashTool, BLOCKED_PATTERNS
from rein.tools.search_tools import GrepTool, GlobTool


# --- Helper ---

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class DummyTool(BaseTool):
    @property
    def name(self) -> str:
        return "Dummy"

    @property
    def description(self) -> str:
        return "A dummy tool."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, params: dict[str, Any]) -> str:
        return "dummy result"


# --- ToolRegistry ---

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool()
        reg.register(tool)
        assert reg.get("Dummy") is tool
        assert "Dummy" in reg.list_names()

    def test_get_nonexistent(self):
        reg = ToolRegistry()
        assert reg.get("NoSuchTool") is None

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        reg.unregister("Dummy")
        assert reg.get("Dummy") is None

    def test_get_schemas(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        schemas = reg.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "Dummy"
        assert "description" in schemas[0]
        assert "input_schema" in schemas[0]


# --- ReadTool ---

class TestReadTool:
    def test_read_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            tool = ReadTool()
            result = run(tool.execute({"file_path": f.name}))
            assert "1\tline1" in result
            assert "2\tline2" in result

    def test_read_with_offset_limit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("a\nb\nc\nd\ne\n")
            f.flush()
            tool = ReadTool()
            result = run(tool.execute({"file_path": f.name, "offset": 1, "limit": 2}))
            assert "2\tb" in result
            assert "3\tc" in result
            assert "1\ta" not in result

    def test_read_missing_file(self):
        tool = ReadTool()
        result = run(tool.execute({"file_path": "/nonexistent/file.txt"}))
        assert "Error" in result

    def test_read_directory(self):
        tool = ReadTool()
        result = run(tool.execute({"file_path": tempfile.mkdtemp()}))
        assert "Error" in result


# --- WriteTool ---

class TestWriteTool:
    def test_write_new_file(self):
        path = Path(tempfile.mkdtemp()) / "test.txt"
        tool = WriteTool()
        result = run(tool.execute({"file_path": str(path), "content": "hello world"}))
        assert "Successfully" in result
        assert path.read_text() == "hello world"

    def test_write_creates_parent_dirs(self):
        path = Path(tempfile.mkdtemp()) / "sub" / "dir" / "test.txt"
        tool = WriteTool()
        result = run(tool.execute({"file_path": str(path), "content": "nested"}))
        assert "Successfully" in result
        assert path.read_text() == "nested"


# --- EditTool ---

class TestEditTool:
    def test_edit_replace(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            f.flush()
            tool = EditTool()
            result = run(tool.execute({
                "file_path": f.name,
                "old_string": "world",
                "new_string": "ReIN",
            }))
            assert "Successfully" in result
            assert Path(f.name).read_text() == "hello ReIN"

    def test_edit_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            f.flush()
            tool = EditTool()
            result = run(tool.execute({
                "file_path": f.name,
                "old_string": "nonexistent",
                "new_string": "replacement",
            }))
            assert "Error" in result

    def test_edit_multiple_matches_blocked(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("aaa bbb aaa")
            f.flush()
            tool = EditTool()
            result = run(tool.execute({
                "file_path": f.name,
                "old_string": "aaa",
                "new_string": "ccc",
            }))
            assert "Error" in result
            assert "2 times" in result

    def test_edit_replace_all(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("aaa bbb aaa")
            f.flush()
            tool = EditTool()
            result = run(tool.execute({
                "file_path": f.name,
                "old_string": "aaa",
                "new_string": "ccc",
                "replace_all": True,
            }))
            assert "Successfully" in result
            assert Path(f.name).read_text() == "ccc bbb ccc"


# --- BashTool security ---

class TestBashToolSecurity:
    def test_blocks_rm_rf_root(self):
        tool = BashTool()
        result = run(tool.execute({"command": "rm -rf /"}))
        assert "blocked" in result.lower()

    def test_blocks_fork_bomb(self):
        tool = BashTool()
        result = run(tool.execute({"command": ":(){ :|:& };"}))
        assert "blocked" in result.lower()

    def test_blocks_mkfs(self):
        tool = BashTool()
        result = run(tool.execute({"command": "mkfs.ext4 /dev/sda"}))
        assert "blocked" in result.lower()

    def test_blocks_dd_to_device(self):
        tool = BashTool()
        result = run(tool.execute({"command": "dd if=/dev/zero of=/dev/sda"}))
        assert "blocked" in result.lower()

    def test_allows_safe_command(self):
        tool = BashTool()
        result = run(tool.execute({"command": "echo hello"}))
        assert "hello" in result

    def test_allowed_patterns_filter(self):
        tool = BashTool(allowed_patterns=["git:*"])
        result = run(tool.execute({"command": "rm -rf ."}))
        assert "not in allowed patterns" in result.lower()

    def test_allowed_patterns_pass(self):
        tool = BashTool(allowed_patterns=["echo:*", "*"])
        result = run(tool.execute({"command": "echo test"}))
        assert "test" in result

    def test_timeout(self):
        tool = BashTool()
        result = run(tool.execute({"command": "sleep 10", "timeout": 1}))
        assert "timed out" in result.lower()


# --- GrepTool ---

class TestGrepTool:
    def test_grep_finds_match(self):
        d = Path(tempfile.mkdtemp())
        (d / "test.py").write_text("def hello():\n    return 42\n")
        tool = GrepTool()
        result = run(tool.execute({"pattern": "hello", "path": str(d)}))
        assert "hello" in result
        assert "test.py" in result

    def test_grep_no_match(self):
        d = Path(tempfile.mkdtemp())
        (d / "test.py").write_text("nothing here\n")
        tool = GrepTool()
        result = run(tool.execute({"pattern": "nonexistent", "path": str(d)}))
        assert "No matches" in result

    def test_grep_invalid_regex(self):
        tool = GrepTool()
        result = run(tool.execute({"pattern": "[invalid", "path": tempfile.mkdtemp()}))
        assert "Error" in result


# --- GlobTool ---

class TestGlobTool:
    def test_glob_finds_files(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        (d / "b.txt").write_text("x")
        tool = GlobTool()
        result = run(tool.execute({"pattern": "*.py", "path": str(d)}))
        assert "a.py" in result
        assert "b.txt" not in result

    def test_glob_no_match(self):
        d = Path(tempfile.mkdtemp())
        tool = GlobTool()
        result = run(tool.execute({"pattern": "*.xyz", "path": str(d)}))
        assert "No files found" in result
