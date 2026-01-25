"""Navigation backends for phase 2 walkthroughs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from repowalk.repo_scout.tools import RepoScoutTools


@dataclass
class TraceTarget:
    """Resolved definition or symbol to continue tracing."""

    name: str
    location: str
    kind: str
    preview: str = ""
    calls_to: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    content: Optional[str] = None


@dataclass
class BranchPoint:
    """Decision point with multiple candidate targets."""

    location: str
    options: List[TraceTarget]


@dataclass
class TraceContext:
    """Track trace state for lazy generation."""

    current_location: str
    depth: int
    max_depth: int
    visited: Set[str] = field(default_factory=set)
    branch_points: List[BranchPoint] = field(default_factory=list)


class NavigationBackend:
    """Interface for tracing navigation."""

    def find_next_steps(self, location: str, max_results: int = 5) -> List[TraceTarget]:
        raise NotImplementedError


class SearchNavigationBackend(NavigationBackend):
    """Heuristic navigation using file reads + regex search."""

    _definition_patterns: Sequence[Tuple[re.Pattern, str]] = (
        (re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
        (re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"), "class"),
        (re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
        (re.compile(r"^\s*export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
        (re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\("), "function"),
        (re.compile(r"^\s*let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\("), "function"),
        (re.compile(r"^\s*var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\("), "function"),
        (re.compile(r"^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
        (re.compile(r"^\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)"), "function"),
        (re.compile(r"^\s*struct\s+([A-Za-z_][A-Za-z0-9_]*)"), "struct"),
        (re.compile(r"^\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)"), "interface"),
    )

    _call_pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    _call_stopwords = {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "yield",
        "await",
        "new",
        "delete",
        "sizeof",
        "typeof",
        "print",
        "len",
        "list",
        "dict",
        "set",
        "map",
        "filter",
        "reduce",
        "super",
        "this",
        "self",
        "console",
        "log",
        "error",
        "debug",
        "warn",
    }

    def __init__(self, repo_path: Path, scope_window: int = 80, preview_lines: int = 6):
        self.repo_path = Path(repo_path).resolve()
        self.tools = RepoScoutTools(self.repo_path)
        self.scope_window = scope_window
        self.preview_lines = preview_lines
        self._definition_cache: dict[str, Optional[TraceTarget]] = {}

    def find_next_steps(self, location: str, max_results: int = 5) -> List[TraceTarget]:
        path, line_number = _parse_location(location)
        if not path:
            return []

        content = self._read_file(path)
        if content is None:
            return []

        lines = content.splitlines()
        if not lines:
            return []

        line_index = 0
        if line_number is not None:
            line_index = max(0, min(len(lines) - 1, line_number - 1))

        def_info = _find_enclosing_definition(lines, line_index, self._definition_patterns)
        if def_info is None:
            def_info = _find_first_definition(lines, self._definition_patterns)

        if def_info is None:
            return self._fallback_definitions(path, lines, max_results)

        name, kind, def_line_index = def_info
        scope_lines = lines[def_line_index : min(len(lines), def_line_index + self.scope_window)]
        call_names = _extract_call_names(scope_lines, self._call_pattern, self._call_stopwords)
        if name:
            call_names = [call for call in call_names if call != name]

        targets: List[TraceTarget] = []
        for call_name in call_names:
            target = self._resolve_symbol(call_name, path, lines)
            if target:
                targets.append(target)
            if len(targets) >= max_results:
                break

        if not targets:
            targets = self._fallback_definitions(path, lines, max_results)

        return targets

    def _fallback_definitions(self, path: str, lines: List[str], max_results: int) -> List[TraceTarget]:
        targets: List[TraceTarget] = []
        for line_index, line in enumerate(lines):
            for pattern, kind in self._definition_patterns:
                match = pattern.match(line)
                if match:
                    name = match.group(1)
                    location = f"{path}:{line_index + 1}"
                    preview = line.strip()
                    scope_lines = lines[
                        line_index : min(len(lines), line_index + self.scope_window)
                    ]
                    calls_to = _extract_call_names(
                        scope_lines, self._call_pattern, self._call_stopwords
                    )
                    content = "\n".join(scope_lines[: self.preview_lines])
                    targets.append(
                        TraceTarget(
                            name=name,
                            location=location,
                            kind=kind,
                            preview=preview,
                            calls_to=calls_to,
                            content=content,
                        )
                    )
                    break
            if len(targets) >= max_results:
                break
        return targets

    def _resolve_symbol(self, name: str, path: str, lines: List[str]) -> Optional[TraceTarget]:
        if name in self._definition_cache:
            return self._definition_cache[name]

        resolved = self._resolve_in_file(name, path, lines)
        if resolved:
            self._definition_cache[name] = resolved
            return resolved

        pattern = _build_definition_search_pattern(name)
        result = self.tools.search_text(pattern)
        if not result.ok or not result.output:
            self._definition_cache[name] = None
            return None

        first = result.output.splitlines()[0]
        parsed = _parse_search_result(first)
        if not parsed:
            self._definition_cache[name] = None
            return None

        match_path, line_number, line_text = parsed
        kind = _infer_kind_from_line(line_text)
        location = f"{match_path}:{line_number}"
        preview = line_text.strip()
        content = preview
        range_result = self.tools.read_file_range(
            match_path,
            start_line=max(1, line_number - 1),
            end_line=line_number + self.preview_lines,
        )
        if range_result.ok and range_result.output:
            content = range_result.output
        target = TraceTarget(
            name=name,
            location=location,
            kind=kind,
            preview=preview,
            content=content,
        )
        self._definition_cache[name] = target
        return target

    def _resolve_in_file(self, name: str, path: str, lines: List[str]) -> Optional[TraceTarget]:
        for line_index, line in enumerate(lines):
            if _line_defines_symbol(line, name):
                kind = _infer_kind_from_line(line)
                location = f"{path}:{line_index + 1}"
                preview = line.strip()
                scope_lines = lines[
                    line_index : min(len(lines), line_index + self.scope_window)
                ]
                calls_to = _extract_call_names(
                    scope_lines, self._call_pattern, self._call_stopwords
                )
                content = "\n".join(scope_lines[: self.preview_lines])
                return TraceTarget(
                    name=name,
                    location=location,
                    kind=kind,
                    preview=preview,
                    calls_to=calls_to,
                    content=content,
                )
        return None

    def _read_file(self, rel_path: str) -> Optional[str]:
        result = self.tools.read_file(rel_path)
        if result.ok:
            return result.output
        return None


def _parse_location(location: str) -> Tuple[str, Optional[int]]:
    if not location:
        return "", None
    if "#L" in location:
        path, line = location.split("#L", 1)
        if line.isdigit():
            return path, int(line)
        return path, None
    if ":" in location:
        path, tail = location.rsplit(":", 1)
        if tail.isdigit():
            return path, int(tail)
    return location, None


def _find_enclosing_definition(
    lines: Sequence[str],
    line_index: int,
    patterns: Sequence[Tuple[re.Pattern, str]],
) -> Optional[Tuple[str, str, int]]:
    for idx in range(line_index, -1, -1):
        line = lines[idx]
        for pattern, kind in patterns:
            match = pattern.match(line)
            if match:
                return match.group(1), kind, idx
    return None


def _find_first_definition(
    lines: Sequence[str],
    patterns: Sequence[Tuple[re.Pattern, str]],
) -> Optional[Tuple[str, str, int]]:
    for idx, line in enumerate(lines):
        for pattern, kind in patterns:
            match = pattern.match(line)
            if match:
                return match.group(1), kind, idx
    return None


def _extract_call_names(
    lines: Iterable[str],
    call_pattern: re.Pattern,
    stopwords: Set[str],
) -> List[str]:
    seen: Set[str] = set()
    calls: List[str] = []
    for line in lines:
        for match in call_pattern.finditer(line):
            name = match.group(1)
            if name in stopwords:
                continue
            if name in seen:
                continue
            seen.add(name)
            calls.append(name)
    return calls


def _line_defines_symbol(line: str, name: str) -> bool:
    escaped = re.escape(name)
    patterns = [
        rf"\bdef\s+{escaped}\b",
        rf"\bclass\s+{escaped}\b",
        rf"\bfunction\s+{escaped}\b",
        rf"\bfunc\s+{escaped}\b",
        rf"\bfn\s+{escaped}\b",
        rf"\bstruct\s+{escaped}\b",
        rf"\binterface\s+{escaped}\b",
        rf"\bconst\s+{escaped}\b",
        rf"\blet\s+{escaped}\b",
        rf"\bvar\s+{escaped}\b",
    ]
    return any(re.search(pattern, line) for pattern in patterns)


def _build_definition_search_pattern(name: str) -> str:
    escaped = re.escape(name)
    return (
        rf"\b(def|class|function|func|fn|struct|interface)\s+{escaped}\b"
        rf"|\b(const|let|var)\s+{escaped}\b"
    )


def _parse_search_result(line: str) -> Optional[Tuple[str, int, str]]:
    parts = line.split(":", 2)
    if len(parts) < 3:
        return None
    path, line_number, text = parts
    if not line_number.isdigit():
        return None
    return path, int(line_number), text


def _infer_kind_from_line(line: str) -> str:
    lowered = line.strip().lower()
    if lowered.startswith("class ") or " class " in lowered:
        return "class"
    if lowered.startswith("struct ") or " struct " in lowered:
        return "struct"
    if lowered.startswith("interface ") or " interface " in lowered:
        return "interface"
    if "def " in lowered or "function " in lowered or "func " in lowered or "fn " in lowered:
        return "function"
    return "symbol"
