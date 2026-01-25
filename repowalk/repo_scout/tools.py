"""File system tools for repo scouting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import List, Optional

from .filters import TEXT_EXTENSIONS, should_skip_path


@dataclass
class ToolResult:
    ok: bool
    output: str
    error: Optional[str] = None


@dataclass
class RepoScoutTools:
    repo_path: Path
    max_file_bytes: int = 200_000
    max_results: int = 50
    tool_calls_used: int = 0
    files_read: List[str] = field(default_factory=list)

    def _resolve(self, rel_path: str) -> Path:
        target = (self.repo_path / rel_path).resolve()
        if not str(target).startswith(str(self.repo_path.resolve())):
            raise ValueError("Path traversal detected")
        return target

    def read_file(self, rel_path: str, max_lines: Optional[int] = None) -> ToolResult:
        self.tool_calls_used += 1
        try:
            target = self._resolve(rel_path)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if not target.exists():
            return ToolResult(ok=False, output="", error="File does not exist")
        if should_skip_path(target, self.repo_path):
            return ToolResult(ok=False, output="", error="File is skipped")

        try:
            content = target.read_text(errors="replace")
        except OSError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if max_lines is not None:
            content = "\n".join(content.splitlines()[:max_lines])

        if len(content.encode("utf-8")) > self.max_file_bytes:
            content = content[: self.max_file_bytes]

        self.files_read.append(rel_path)
        return ToolResult(ok=True, output=content)

    def read_file_range(self, rel_path: str, start_line: int, end_line: int) -> ToolResult:
        self.tool_calls_used += 1
        try:
            target = self._resolve(rel_path)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if not target.exists():
            return ToolResult(ok=False, output="", error="File does not exist")

        try:
            lines = target.read_text(errors="replace").split("\n")
        except OSError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        start = max(0, start_line - 1)
        end = len(lines) if end_line == -1 else min(len(lines), end_line)
        selected = lines[start:end]
        numbered = [f"{start + i + 1:4d} | {line}" for i, line in enumerate(selected)]
        result = "\n".join(numbered)
        if start > 0:
            result = f"[... {start} lines above ...]\n" + result
        if end < len(lines):
            result = result + f"\n[... {len(lines) - end} lines below ...]"

        self.files_read.append(rel_path)
        return ToolResult(ok=True, output=result)

    def read_file_head_tail(self, rel_path: str, head_lines: int = 50, tail_lines: int = 50) -> ToolResult:
        self.tool_calls_used += 1
        try:
            target = self._resolve(rel_path)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if not target.exists():
            return ToolResult(ok=False, output="", error="File does not exist")

        try:
            lines = target.read_text(errors="replace").split("\n")
        except OSError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if len(lines) <= head_lines + tail_lines:
            numbered = [f"{i + 1:4d} | {line}" for i, line in enumerate(lines)]
            result = "\n".join(numbered)
            self.files_read.append(rel_path)
            return ToolResult(ok=True, output=result)

        head = lines[:head_lines]
        tail = lines[-tail_lines:]
        skipped = len(lines) - head_lines - tail_lines
        head_str = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(head))
        tail_str = "\n".join(
            f"{len(lines) - tail_lines + i + 1:4d} | {line}" for i, line in enumerate(tail)
        )
        result = f"{head_str}\n\n[... {skipped} lines skipped ...]\n\n{tail_str}"
        self.files_read.append(rel_path)
        return ToolResult(ok=True, output=result)

    def search_text(self, query: str, file_pattern: Optional[str] = None) -> ToolResult:
        self.tool_calls_used += 1
        pattern = re.compile(query)
        results: List[str] = []

        for path in self.repo_path.rglob("*"):
            if should_skip_path(path, self.repo_path):
                continue
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            if file_pattern and not path.match(file_pattern):
                continue
            try:
                for i, line in enumerate(path.read_text(errors="replace").split("\n")):
                    if pattern.search(line):
                        rel = path.relative_to(self.repo_path)
                        results.append(f"{rel}:{i + 1}: {line.strip()}")
                        if len(results) >= self.max_results:
                            return ToolResult(ok=True, output="\n".join(results))
            except OSError:
                continue

        return ToolResult(ok=True, output="\n".join(results))

    def list_directory(self, rel_path: str) -> ToolResult:
        self.tool_calls_used += 1
        try:
            target = self._resolve(rel_path)
        except ValueError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if not target.exists():
            return ToolResult(ok=False, output="", error="Path does not exist")
        if not target.is_dir():
            return ToolResult(ok=False, output="", error="Path is not a directory")

        entries = []
        for entry in target.iterdir():
            if should_skip_path(entry, self.repo_path):
                continue
            entries.append(entry.name + ("/" if entry.is_dir() else ""))

        return ToolResult(ok=True, output="\n".join(sorted(entries)))
