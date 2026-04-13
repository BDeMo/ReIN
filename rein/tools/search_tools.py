"""Search tools: Grep and Glob."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from .registry import BaseTool


class GrepTool(BaseTool):
    """Search file contents with regex."""

    @property
    def name(self) -> str:
        return "Grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents using regex patterns. "
            "Returns matching lines with file paths and line numbers."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in (default: cwd).",
                },
                "glob": {
                    "type": "string",
                    "description": "File glob filter (e.g. '*.py', '*.ts').",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search.",
                    "default": False,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results.",
                    "default": 200,
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        pattern = params["pattern"]
        search_path = Path(params.get("path", os.getcwd()))
        glob_filter = params.get("glob")
        case_insensitive = params.get("case_insensitive", False)
        max_results = params.get("max_results", 200)

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        results: list[str] = []

        if search_path.is_file():
            files = [search_path]
        else:
            files = self._find_files(search_path, glob_filter)

        for file_path in files:
            if len(results) >= max_results:
                break
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{file_path}:{i}: {line.rstrip()}")
                        if len(results) >= max_results:
                            break
            except (PermissionError, OSError):
                continue

        if not results:
            return "No matches found."

        output = "\n".join(results)
        if len(results) >= max_results:
            output += f"\n\n(showing first {max_results} results)"
        return output

    def _find_files(self, root: Path, glob_filter: str | None, max_files: int = 5000) -> list[Path]:
        """Walk directory tree finding text files."""
        files: list[Path] = []
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build"}

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fname in filenames:
                if len(files) >= max_files:
                    return files
                fpath = Path(dirpath) / fname
                if glob_filter and not fnmatch.fnmatch(fname, glob_filter):
                    continue
                # Skip binary-looking files
                if fpath.suffix.lower() in {".pyc", ".exe", ".dll", ".so", ".o", ".a",
                                              ".zip", ".tar", ".gz", ".jpg", ".png",
                                              ".gif", ".pdf", ".woff", ".woff2", ".ttf"}:
                    continue
                files.append(fpath)
        return files


class GlobTool(BaseTool):
    """Find files by glob pattern."""

    @property
    def name(self) -> str:
        return "Glob"

    @property
    def description(self) -> str:
        return "Find files matching a glob pattern. Returns file paths sorted by modification time."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory (default: cwd).",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        pattern = params["pattern"]
        base = Path(params.get("path", os.getcwd()))

        try:
            matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        except (OSError, ValueError) as e:
            return f"Error: {e}"

        if not matches:
            return "No files found."

        # Limit output
        max_show = 500
        lines = [str(m) for m in matches[:max_show]]
        output = "\n".join(lines)
        if len(matches) > max_show:
            output += f"\n\n(showing {max_show} of {len(matches)} matches)"
        return output
