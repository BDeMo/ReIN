"""File I/O tools: Read, Write, Edit."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .registry import BaseTool


class ReadTool(BaseTool):
    """Read file contents with optional line range."""

    @property
    def name(self) -> str:
        return "Read"

    @property
    def description(self) -> str:
        return (
            "Read a file from the filesystem. Returns contents with line numbers. "
            "Supports offset/limit for reading specific line ranges."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based).",
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of lines to read.",
                    "minimum": 1,
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        file_path = params["file_path"]
        offset = params.get("offset", 0)
        limit = params.get("limit")

        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"
        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied: {file_path}"

        lines = text.splitlines(keepends=True)
        total = len(lines)

        if offset >= total:
            return f"Error: offset {offset} is beyond file length ({total} lines)"

        end = min(offset + limit, total) if limit else total
        selected = lines[offset:end]

        # Format with line numbers (1-based)
        output_lines = []
        for i, line in enumerate(selected, start=offset + 1):
            output_lines.append(f"{i}\t{line.rstrip()}")

        return "\n".join(output_lines)


class WriteTool(BaseTool):
    """Write content to a file (creates or overwrites)."""

    @property
    def name(self) -> str:
        return "Write"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        file_path = params["file_path"]
        content = params["content"]

        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {file_path}"
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except OSError as e:
            return f"Error writing file: {e}"


class EditTool(BaseTool):
    """Edit a file by replacing a specific string."""

    @property
    def name(self) -> str:
        return "Edit"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing an exact string match. The old_string must "
            "appear exactly once in the file (unless replace_all is true)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file.",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace.",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement string.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false).",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        file_path = params["file_path"]
        old_string = params["old_string"]
        new_string = params["new_string"]
        replace_all = params.get("replace_all", False)

        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        try:
            content = path.read_text(encoding="utf-8")
        except PermissionError:
            return f"Error: Permission denied: {file_path}"

        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1 and not replace_all:
            return (
                f"Error: old_string appears {count} times in {file_path}. "
                "Provide a larger unique string or set replace_all=true."
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        path.write_text(new_content, encoding="utf-8")
        replacements = count if replace_all else 1
        return f"Successfully edited {file_path} ({replacements} replacement(s))"
