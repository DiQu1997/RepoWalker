from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import fnmatch
import json
import os
import re
import shutil
import subprocess

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - handled at runtime
    OpenAI = None

from .orientation import (
    build_exploration_prompt,
    build_plan_prompt,
    build_step_explanation_prompt,
)


@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None


class Phase(Enum):
    EXPLORE = "explore"
    PLAN = "plan"
    WALK = "walk"
    COMPLETE = "complete"


@dataclass
class WalkStep:
    step_number: int
    title: str
    file_path: str
    function_or_section: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    why_important: Optional[str] = None
    data_structures: List[str] = field(default_factory=list)
    key_concepts: List[str] = field(default_factory=list)
    leads_to: Optional[str] = None


@dataclass
class WalkPlan:
    title: str
    overview: str
    steps: List[WalkStep]
    total_steps: int


@dataclass
class ExplorationContext:
    repo_structure: Optional[str] = None
    readme_content: Optional[str] = None
    key_files: List[Dict] = field(default_factory=list)
    entry_points: List[Dict] = field(default_factory=list)
    relevant_searches: List[Dict] = field(default_factory=list)
    data_structures_found: List[Dict] = field(default_factory=list)
    outlines: List[Dict] = field(default_factory=list)


@dataclass
class AgentState:
    user_request: str
    repo_path: str
    phase: Phase = Phase.EXPLORE
    exploration: ExplorationContext = field(default_factory=ExplorationContext)
    plan: Optional[WalkPlan] = None
    current_step: int = 0
    thinking_history: List[Dict] = field(default_factory=list)
    tool_calls: List[Dict] = field(default_factory=list)


class LLMClient:
    def __init__(self, model: str):
        _load_env_file(Path.home() / ".env")
        if OpenAI is None:
            raise RuntimeError(
                "openai package not installed. Install with `pip install openai`."
            )
        self.client = OpenAI()
        self.model = model

    def generate(self, messages: List[Dict], max_output_tokens: int) -> str:
        if hasattr(self.client, "responses"):
            response = self.client.responses.create(
                model=self.model,
                input=messages,
                max_output_tokens=max_output_tokens,
            )
            return self._extract_response_text(response)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_output_tokens,
        )
        return response.choices[0].message.content or ""

    def _extract_response_text(self, response) -> str:
        text = getattr(response, "output_text", None)
        if text:
            return text
        output = getattr(response, "output", None)
        if output:
            parts: List[str] = []
            for item in output:
                content = getattr(item, "content", None)
                if not content:
                    continue
                for block in content:
                    block_type = getattr(block, "type", None)
                    if block_type in ("output_text", "text"):
                        parts.append(getattr(block, "text", ""))
            if parts:
                return "".join(parts)
        try:
            return response.output[0].content[0].text
        except Exception:
            return ""


def _load_env_file(path: Path) -> None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value


class CodeWalkerTools:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self._validate_repo()
        self._rg_available = shutil.which("rg") is not None
        self._file_available = shutil.which("file") is not None
        self._ignore_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            ".mypy_cache",
            ".pytest_cache",
            ".tox",
            "dist",
            "build",
            "target",
        }

    # ===== File System Tools =====

    def tree(
        self, path: str = ".", max_depth: int = 3, include_hidden: bool = False
    ) -> ToolResult:
        target = self._resolve_path(path)
        if not target.exists():
            return ToolResult(False, "", f"Path not found: {path}")

        lines: List[str] = [self._format_path(target)]

        def walk(current: Path, prefix: str, depth: int) -> None:
            if depth >= max_depth:
                return
            try:
                entries = sorted(
                    current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
                )
            except PermissionError:
                lines.append(f"{prefix}\\-- [permission denied]")
                return
            filtered: List[Path] = []
            for entry in entries:
                name = entry.name
                if not include_hidden and name.startswith("."):
                    continue
                if name in self._ignore_dirs:
                    continue
                if name.endswith(".pyc"):
                    continue
                filtered.append(entry)
            for index, entry in enumerate(filtered):
                is_last = index == len(filtered) - 1
                connector = "\\--" if is_last else "|--"
                lines.append(f"{prefix}{connector} {entry.name}")
                if entry.is_dir():
                    extension = "    " if is_last else "|   "
                    walk(entry, prefix + extension, depth + 1)

        if target.is_dir():
            walk(target, "", 0)
        return ToolResult(True, "\n".join(lines))

    def read_file(
        self, path: str, start_line: int = None, end_line: int = None
    ) -> ToolResult:
        target = self._resolve_path(path)
        if not target.exists():
            return ToolResult(False, "", f"File not found: {path}")
        if not target.is_file():
            return ToolResult(False, "", f"Not a file: {path}")
        try:
            content = self._read_text(target)
            lines = content.split("\n")
            start = max(0, (start_line or 1) - 1)
            end = end_line if end_line is not None else len(lines)
            end = min(len(lines), end)
            slice_lines = lines[start:end]
            numbered = [
                f"{i + start + 1:4d} | {line}" for i, line in enumerate(slice_lines)
            ]
            return ToolResult(True, "\n".join(numbered))
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    def list_dir(self, path: str = ".") -> ToolResult:
        target = self._resolve_path(path)
        if not target.exists():
            return ToolResult(False, "", f"Path not found: {path}")
        if not target.is_dir():
            return ToolResult(False, "", f"Not a directory: {path}")
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
        lines: List[str] = []
        for entry in entries:
            stat = entry.stat()
            kind = "d" if entry.is_dir() else "-"
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(
                timespec="seconds"
            )
            lines.append(f"{kind} {size:>10} {mtime} {entry.name}")
        return ToolResult(True, "\n".join(lines))

    def file_info(self, path: str) -> ToolResult:
        target = self._resolve_path(path)
        if not target.exists():
            return ToolResult(False, "", f"Path not found: {path}")
        output = ""
        if self._file_available:
            result = self._run(["file", str(target)], allow_empty=False)
            if result.success:
                output = result.output
            else:
                output = f"{target}: (file info unavailable)"
        else:
            output = f"{target}: (file command unavailable)"
        stat = target.stat()
        output += f"\nSize: {stat.st_size} bytes"
        output += (
            "\nModified: "
            + datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        )
        return ToolResult(True, output)

    # ===== Search Tools =====

    def grep(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: str = None,
        context_lines: int = 2,
        ignore_case: bool = False,
    ) -> ToolResult:
        target = self._resolve_path(path)
        if self._rg_available:
            cmd = ["rg", "-n", f"-C{context_lines}"]
            if ignore_case:
                cmd.append("-i")
            for glob in [
                "**/.git/**",
                "**/node_modules/**",
                "**/__pycache__/**",
                "**/.venv/**",
                "**/venv/**",
                "**/target/**",
                "**/build/**",
                "**/dist/**",
            ]:
                cmd.extend(["-g", f"!{glob}"])
            if file_pattern:
                cmd.extend(["-g", file_pattern])
            cmd.extend([pattern, str(target)])
            return self._run(cmd, allow_empty=True)
        return self._python_grep(
            pattern, target, file_pattern, context_lines, ignore_case
        )

    def git_grep(self, pattern: str, file_pattern: str = None) -> ToolResult:
        if not (self.repo_path / ".git").exists():
            return self.grep(pattern, path=".", file_pattern=file_pattern)
        cmd = ["git", "-C", str(self.repo_path), "grep", "-n", "--heading", pattern]
        if file_pattern:
            cmd.extend(["--", file_pattern])
        return self._run(cmd, allow_empty=True)

    def find_files(self, name_pattern: str, file_type: str = "f") -> ToolResult:
        results: List[str] = []
        if file_type == "d":
            for dirpath, dirnames, _ in os.walk(self.repo_path):
                dirnames[:] = [
                    d for d in dirnames if not self._should_skip_dir(d)
                ]
                for name in dirnames:
                    if fnmatch.fnmatch(name, name_pattern):
                        path = Path(dirpath) / name
                        results.append(self._format_path(path))
        else:
            for path in self._iter_files(self.repo_path, name_pattern):
                results.append(self._format_path(path))
        if not results:
            return ToolResult(True, "(no matches)")
        return ToolResult(True, "\n".join(sorted(results)))

    def find_definition(self, symbol: str, language: str = None) -> ToolResult:
        sym = re.escape(symbol)
        patterns = {
            "python": [
                rf"\bdef\s+{sym}\s*\(",
                rf"\bclass\s+{sym}\b",
                rf"^{sym}\s*=",
            ],
            "go": [
                rf"\bfunc\s+{sym}\s*\(",
                rf"\bfunc\s+\([^)]+\)\s+{sym}\s*\(",
                rf"\btype\s+{sym}\b",
            ],
            "javascript": [
                rf"\bfunction\s+{sym}\s*\(",
                rf"\bconst\s+{sym}\s*=",
                rf"\bclass\s+{sym}\b",
                rf"\b{sym}\s*:\s*function\b",
            ],
            "java": [
                rf"\bclass\s+{sym}\b",
                rf"\binterface\s+{sym}\b",
                rf"\b{sym}\s*\(",
            ],
            "rust": [
                rf"\bfn\s+{sym}\s*\(",
                rf"\bstruct\s+{sym}\b",
                rf"\benum\s+{sym}\b",
                rf"\bimpl\s+{sym}\b",
            ],
            "cpp": [
                rf"\bclass\s+{sym}\b",
                rf"\bstruct\s+{sym}\b",
                rf"\b{sym}\s*\(",
            ],
        }
        if language and language in patterns:
            search_patterns = patterns[language]
        else:
            search_patterns = []
            for lang_patterns in patterns.values():
                search_patterns.extend(lang_patterns)
        results: List[str] = []
        for pattern in search_patterns:
            result = self.grep(pattern, context_lines=3)
            if result.success and result.output not in (
                "",
                "(no matches)",
                "(empty output)",
            ):
                results.append(result.output)
        if results:
            return ToolResult(True, "\n---\n".join(results))
        return ToolResult(True, f"No definition found for: {symbol}")

    def find_usages(self, symbol: str) -> ToolResult:
        return self.grep(symbol, context_lines=1)

    # ===== Code Analysis Tools =====

    def get_function(self, file_path: str, function_name: str) -> ToolResult:
        result = self.read_file(file_path)
        if not result.success:
            return result
        lines = result.output.split("\n")
        in_function = False
        function_lines: List[str] = []
        base_indent = 0
        for line in lines:
            if " | " in line:
                _, code = line.split(" | ", 1)
            else:
                code = line
            if not in_function:
                if self._is_function_def(code, function_name):
                    in_function = True
                    base_indent = len(code) - len(code.lstrip())
                    function_lines.append(line)
            else:
                stripped = code.strip()
                if stripped:
                    current_indent = len(code) - len(code.lstrip())
                    if current_indent <= base_indent and self._is_new_definition(code):
                        break
                function_lines.append(line)
        if function_lines:
            return ToolResult(True, "\n".join(function_lines))
        return ToolResult(False, "", f"Function not found: {function_name}")

    def get_class(self, file_path: str, class_name: str) -> ToolResult:
        result = self.read_file(file_path)
        if not result.success:
            return result
        lines = result.output.split("\n")
        in_class = False
        class_lines: List[str] = []
        base_indent = 0
        for line in lines:
            if " | " in line:
                _, code = line.split(" | ", 1)
            else:
                code = line
            if not in_class:
                if (
                    f"class {class_name}" in code
                    or f"struct {class_name}" in code
                    or f"type {class_name}" in code
                ):
                    in_class = True
                    base_indent = len(code) - len(code.lstrip())
                    class_lines.append(line)
            else:
                stripped = code.strip()
                if stripped:
                    current_indent = len(code) - len(code.lstrip())
                    if current_indent <= base_indent and self._is_new_definition(code):
                        break
                class_lines.append(line)
        if class_lines:
            return ToolResult(True, "\n".join(class_lines))
        return ToolResult(False, "", f"Class not found: {class_name}")

    def get_imports(self, file_path: str) -> ToolResult:
        result = self.read_file(file_path)
        if not result.success:
            return result
        import_patterns = [
            r"^import\s+",
            r"^from\s+.*\s+import\s+",
            r"^#include",
            r"^require\(",
            r"^const\s+.*\s+=\s+require\(",
            r"^use\s+",
        ]
        imports: List[str] = []
        for line in result.output.split("\n"):
            if " | " in line:
                _, code = line.split(" | ", 1)
            else:
                code = line
            for pattern in import_patterns:
                if re.match(pattern, code.strip()):
                    imports.append(line)
                    break
        return ToolResult(True, "\n".join(imports) if imports else "No imports found")

    def get_outline(self, file_path: str) -> ToolResult:
        result = self.read_file(file_path)
        if not result.success:
            return result
        outline: List[str] = []
        for line in result.output.split("\n"):
            if " | " not in line:
                continue
            line_num, code = line.split(" | ", 1)
            line_num = line_num.strip()
            stripped = code.strip()
            indent = len(code) - len(code.lstrip())
            if any(
                stripped.startswith(kw)
                for kw in ["class ", "struct ", "type ", "interface "]
            ):
                outline.append(f"L{line_num}: {stripped}")
            elif any(stripped.startswith(kw) for kw in ["def ", "func ", "fn "]):
                prefix = "  " if indent > 0 else ""
                outline.append(f"L{line_num}: {prefix}{stripped.split(':')[0]}")
            elif ("(" in stripped and "):" in stripped) or ") {" in stripped:
                if not any(
                    stripped.startswith(kw)
                    for kw in ["if", "for", "while", "switch", "catch"]
                ):
                    prefix = "  " if indent > 0 else ""
                    outline.append(f"L{line_num}: {prefix}{stripped}")
        return ToolResult(True, "\n".join(outline) if outline else "No outline available")

    # ===== Git Tools =====

    def git_log(self, path: str = None, n: int = 10) -> ToolResult:
        cmd = [
            "git",
            "-C",
            str(self.repo_path),
            "log",
            f"-{n}",
            "--oneline",
            "--date=short",
            "--format=%h %ad %s",
        ]
        if path:
            cmd.extend(["--", path])
        return self._run(cmd)

    def git_show(self, commit: str, file_path: str = None) -> ToolResult:
        cmd = ["git", "-C", str(self.repo_path), "show", "--stat", commit]
        if file_path:
            cmd.extend(["--", file_path])
        return self._run(cmd)

    def git_blame(
        self, file_path: str, start_line: int = None, end_line: int = None
    ) -> ToolResult:
        cmd = ["git", "-C", str(self.repo_path), "blame"]
        if start_line and end_line:
            cmd.extend([f"-L{start_line},{end_line}"])
        cmd.append(file_path)
        return self._run(cmd)

    # ===== Helpers =====

    def _resolve_path(self, path: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(path))
        candidate = Path(expanded)
        if candidate.is_absolute():
            return candidate
        return self.repo_path / expanded

    def _run(self, cmd: List[str], allow_empty: bool = False) -> ToolResult:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.repo_path,
            )
        except FileNotFoundError:
            return ToolResult(False, "", f"Command not found: {cmd[0]}")
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", "Command timed out")
        except Exception as exc:
            return ToolResult(False, "", str(exc))
        if result.returncode == 0:
            output = result.stdout.strip()
            if not output:
                output = "(empty output)"
            return ToolResult(True, output)
        if allow_empty and result.returncode == 1:
            return ToolResult(True, "(no matches)")
        error = result.stderr.strip() or result.stdout.strip()
        if not error:
            error = f"Command failed with exit code {result.returncode}"
        return ToolResult(False, "", error)

    def _validate_repo(self) -> None:
        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {self.repo_path}")

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def _is_function_def(self, code: str, name: str) -> bool:
        patterns = [
            f"def {name}(",
            f"func {name}(",
            f"fn {name}(",
            f"function {name}(",
        ]
        return any(p in code for p in patterns)

    def _is_new_definition(self, code: str) -> bool:
        keywords = ["def ", "class ", "func ", "fn ", "type ", "struct ", "interface "]
        stripped = code.strip()
        return any(stripped.startswith(kw) for kw in keywords)

    def _should_skip_dir(self, name: str) -> bool:
        if name in self._ignore_dirs:
            return True
        if name.startswith("."):
            return True
        return False

    def _iter_files(self, root: Path, file_pattern: Optional[str]) -> Iterable[Path]:
        if root.is_file():
            if file_pattern and not fnmatch.fnmatch(root.name, file_pattern):
                return []
            return [root]
        results: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not self._should_skip_dir(d)]
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                if name.startswith("."):
                    continue
                if file_pattern and not fnmatch.fnmatch(name, file_pattern):
                    continue
                results.append(Path(dirpath) / name)
        return results

    def _is_binary_file(self, path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                chunk = handle.read(2048)
            return b"\0" in chunk
        except Exception:
            return True

    def _python_grep(
        self,
        pattern: str,
        target: Path,
        file_pattern: Optional[str],
        context_lines: int,
        ignore_case: bool,
    ) -> ToolResult:
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return ToolResult(False, "", f"Invalid regex: {exc}")
        matches: List[str] = []
        for file_path in self._iter_files(target, file_pattern):
            if self._is_binary_file(file_path):
                continue
            text = self._read_text(file_path)
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    for j in range(start, end):
                        prefix = ":" if j == i else "-"
                        matches.append(
                            f"{self._format_path(file_path)}:{j + 1}{prefix}{lines[j]}"
                        )
                    matches.append("--")
        if not matches:
            return ToolResult(True, "(no matches)")
        if matches[-1] == "--":
            matches.pop()
        return ToolResult(True, "\n".join(matches))

    def _format_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo_path))
        except ValueError:
            return str(path)


class CodeWalkerAgent:
    TOOL_DESCRIPTIONS = [
        '1. tree(path=".", max_depth=3, include_hidden=False) - Show directory structure',
        "2. read_file(path, start_line=None, end_line=None) - Read file contents",
        "3. grep(pattern, path='.', file_pattern=None, context_lines=2) - Search for pattern",
        "4. git_grep(pattern, file_pattern=None) - Search tracked files",
        "5. find_files(name_pattern, file_type='f') - Find files by name",
        "6. find_definition(symbol, language=None) - Find where symbol is defined",
        "7. find_usages(symbol) - Find all usages of a symbol",
        "8. get_function(file_path, function_name) - Extract complete function",
        "9. get_class(file_path, class_name) - Extract complete class/struct",
        "10. get_imports(file_path) - Get imports from a file",
        "11. get_outline(file_path) - Get structural outline",
        "12. list_dir(path) - List directory contents",
        "13. file_info(path) - File metadata",
        "14. git_log(path=None, n=10) - Recent git history",
        "15. git_show(commit, file_path=None) - Show a commit",
        "16. git_blame(file_path, start_line=None, end_line=None) - Line authorship",
    ]

    def __init__(
        self,
        repo_path: str,
        model: str = "gpt-5.2",
        max_explore_iterations: int = 25,
        verbose: bool = False,
        pause_between_steps: bool = True,
    ):
        self.tools = CodeWalkerTools(repo_path)
        self.client = LLMClient(model=model)
        self.model = model
        self.state: Optional[AgentState] = None
        self.max_explore_iterations = max_explore_iterations
        self.verbose = verbose
        self.pause_between_steps = pause_between_steps

    def run(self, user_request: str) -> None:
        self.prepare_plan(user_request)
        self._walk_phase()

    def prepare_plan(self, user_request: str) -> Optional[WalkPlan]:
        self.state = AgentState(
            user_request=user_request,
            repo_path=str(self.tools.repo_path),
        )
        print(f"\nGoal: {user_request}\n")
        print("=" * 60)
        self._explore_phase()
        self._plan_phase()
        return self.state.plan

    def get_step_code(self, step: WalkStep) -> str:
        return self._get_step_code(step)

    def generate_step_explanation(self, step: WalkStep, code: str) -> str:
        return self._generate_step_explanation(step, code)

    # ===== Phase 1: Explore =====

    def _explore_phase(self) -> None:
        print("\nEXPLORATION PHASE\n")
        self.state.phase = Phase.EXPLORE
        iteration = 0
        while iteration < self.max_explore_iterations:
            iteration += 1
            print(f"--- Thinking (iteration {iteration}) ---")
            action = self._get_next_exploration_action()
            if self._is_redundant_action(action):
                warning = self._build_repeat_warning(action)
                self._log_warning(warning)
                action = self._get_next_exploration_action(repeat_warning=warning)
                if self._is_redundant_action(action):
                    print("\nExploration stalled (repeating tool). Proceeding to plan.\n")
                    return
            if action.get("type") == "done":
                print("\nExploration complete. Ready to plan.\n")
                return
            if action.get("type") != "tool":
                print("\nUnexpected action. Proceeding to plan.\n")
                return
            result = self._execute_tool(action["tool"], action.get("args", {}))
            self._record_tool_call(action, result)
            self._update_exploration_context(action, result)
        print("\nMax iterations reached. Proceeding with available info.\n")

    def _get_next_exploration_action(self, repeat_warning: str | None = None) -> Dict:
        prompt = build_exploration_prompt(
            user_request=self.state.user_request,
            repo_path=self.state.repo_path,
            exploration_context=self._format_exploration_context(),
            tool_descriptions=self.TOOL_DESCRIPTIONS,
            repeat_warning=repeat_warning,
        )
        messages = [
            {
                "role": "system",
                "content": "Return only valid JSON. No prose.",
            },
            {"role": "user", "content": prompt},
        ]
        text = self.client.generate(messages, max_output_tokens=800).strip()
        action = self._parse_json(text)
        if not action:
            print(f"Failed to parse: {text[:200]}")
            return {"type": "done", "reason": "parse error"}
        print(
            f"Action: {action.get('tool', 'done')} - {action.get('reason', '')[:100]}"
        )
        return action

    def _execute_tool(self, tool_name: str, args: Dict) -> ToolResult:
        print(f"  Tool: {tool_name}({args})")
        tool_fn = getattr(self.tools, tool_name, None)
        if not tool_fn:
            return ToolResult(False, "", f"Unknown tool: {tool_name}")
        try:
            result = tool_fn(**args)
            if result.success:
                preview = result.output if self.verbose else result.output[:200]
                if not self.verbose and len(result.output) > 200:
                    preview = preview + "..."
                print(f"  OK: {preview}")
            else:
                print(f"  Error: {result.error}")
            return result
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    def _record_tool_call(self, action: Dict, result: ToolResult) -> None:
        output = result.output
        if len(output) > 4000:
            output = output[:4000] + "... (truncated)"
        self.state.tool_calls.append(
            {
                "tool": action.get("tool"),
                "args": action.get("args", {}),
                "success": result.success,
                "output": output,
                "error": result.error,
            }
        )

    def _update_exploration_context(self, action: Dict, result: ToolResult) -> None:
        if not result.success:
            return
        tool = action.get("tool")
        ctx = self.state.exploration
        if tool == "tree":
            ctx.repo_structure = result.output
        elif tool == "read_file":
            path = action.get("args", {}).get("path", "").lower()
            if "readme" in path:
                ctx.readme_content = result.output
            elif any(x in path for x in ["config", "main", "app", "server"]):
                ctx.key_files.append(
                    {"path": action["args"]["path"], "preview": result.output[:500]}
                )
        elif tool in ["grep", "git_grep", "find_definition"]:
            ctx.relevant_searches.append(
                {
                    "query": action.get("args", {}).get("pattern")
                    or action.get("args", {}).get("symbol"),
                    "results": result.output[:1000],
                }
            )
        elif tool in ["get_class", "get_function"]:
            ctx.data_structures_found.append(
                {
                    "name": action.get("args", {}).get("class_name")
                    or action.get("args", {}).get("function_name"),
                    "file": action.get("args", {}).get("file_path"),
                    "content": result.output,
                }
            )
        elif tool == "get_outline":
            ctx.outlines.append(
                {
                    "file": action.get("args", {}).get("file_path"),
                    "outline": result.output[:2000],
                }
            )

    def _format_exploration_context(self) -> str:
        ctx = self.state.exploration
        parts: List[str] = []
        if ctx.repo_structure:
            parts.append(
                "### Directory Structure\n```\n"
                + ctx.repo_structure[:2000]
                + "\n```"
            )
        if ctx.readme_content:
            parts.append(
                "### README\n```\n" + ctx.readme_content[:2000] + "\n```"
            )
        if ctx.key_files:
            files_text = "\n".join([f"- {f['path']}" for f in ctx.key_files])
            parts.append(f"### Key Files Found\n{files_text}")
        if ctx.relevant_searches:
            searches_text = "\n".join(
                [
                    f"- Search '{s['query']}': {len(s['results'])} chars of results"
                    for s in ctx.relevant_searches[-5:]
                ]
            )
            parts.append(f"### Recent Searches\n{searches_text}")
        if ctx.data_structures_found:
            ds_text = "\n".join(
                [f"- {d['name']} in {d['file']}" for d in ctx.data_structures_found]
            )
            parts.append(f"### Data Structures Found\n{ds_text}")
        if ctx.outlines:
            outline_text = "\n".join(
                [f"- {o['file']}" for o in ctx.outlines[-5:]]
            )
            parts.append(f"### Outlines Captured\n{outline_text}")
        if self.state.tool_calls:
            calls_text = "\n".join(
                [
                    f"- {c['tool']}({c['args']})"
                    for c in self.state.tool_calls[-10:]
                ]
            )
            parts.append(f"### Tool Call History\n{calls_text}")
            outputs_text = "\n\n".join(
                [
                    f"### {c['tool']}({c['args']})\n```\n{(c.get('output') or '')[:1000]}\n```"
                    for c in self.state.tool_calls[-3:]
                ]
            )
            parts.append(f"### Recent Tool Outputs\n{outputs_text}")
        return "\n\n".join(parts) if parts else "(No exploration done yet)"

    # ===== Phase 2: Plan =====

    def _plan_phase(self) -> None:
        print("\nPLANNING PHASE\n")
        self.state.phase = Phase.PLAN
        prompt = build_plan_prompt(
            user_request=self.state.user_request,
            exploration_context=self._format_exploration_context(),
            full_tool_results=self._format_full_tool_results(),
        )
        messages = [
            {
                "role": "system",
                "content": "Return only valid JSON. No prose.",
            },
            {"role": "user", "content": prompt},
        ]
        text = self.client.generate(messages, max_output_tokens=2500).strip()
        plan_data = self._parse_json(text)
        if not plan_data:
            print("Failed to parse plan.")
            print(text[:500])
            return
        steps = []
        for step in plan_data.get("steps", []):
            start_line = self._coerce_int(step.get("start_line"))
            end_line = self._coerce_int(step.get("end_line"))
            steps.append(
                WalkStep(
                    step_number=int(step.get("step_number", len(steps) + 1)),
                    title=step.get("title", ""),
                    file_path=step.get("file_path", ""),
                    function_or_section=step.get("function_or_section"),
                    start_line=start_line,
                    end_line=end_line,
                    why_important=step.get("why_important"),
                    data_structures=step.get("data_structures", []) or [],
                    key_concepts=step.get("key_concepts", []) or [],
                    leads_to=step.get("leads_to"),
                )
            )
        self.state.plan = WalkPlan(
            title=plan_data.get("title", "Code Walk"),
            overview=plan_data.get("overview", ""),
            steps=steps,
            total_steps=len(steps),
        )
        print(f"{self.state.plan.title}")
        print(f"  {self.state.plan.overview}")
        print(f"  ({self.state.plan.total_steps} steps)")

    def _format_full_tool_results(self) -> str:
        parts: List[str] = []
        for call in self.state.tool_calls:
            output = call.get("output") or ""
            parts.append(
                f"### {call.get('tool')}({call.get('args')})\n```\n{output}\n```"
            )
        return "\n\n".join(parts) if parts else "(no tool results)"

    # ===== Phase 3: Walk =====

    def _walk_phase(self) -> None:
        print("\n" + "=" * 60)
        print("CODE WALK-THROUGH")
        print("=" * 60)
        if not self.state.plan:
            print("No plan available.")
            return
        self.state.phase = Phase.WALK
        print(f"\n# {self.state.plan.title}\n")
        print(f"{self.state.plan.overview}\n")
        print("-" * 60)
        for index, step in enumerate(self.state.plan.steps):
            self.state.current_step = index + 1
            self._present_step(step)
            if index < len(self.state.plan.steps) - 1 and self.pause_between_steps:
                input("\n[Press Enter for next step...]\n")
        print("\n" + "=" * 60)
        print("Walk-through complete!")
        print("=" * 60)
        self.state.phase = Phase.COMPLETE

    def _present_step(self, step: WalkStep) -> None:
        print(f"\n## Step {step.step_number}: {step.title}")
        print(f"File: {step.file_path}")
        print()
        code = self._get_step_code(step)
        print("```")
        print(code)

        print("```")
        if step.data_structures:
            print("\nKey Data Structures\n")
            for ds_name in step.data_structures:
                ds_result = self.tools.find_definition(ds_name)
                if ds_result.success and ds_result.output != (
                    f"No definition found for: {ds_name}"
                ):
                    print(f"{ds_name}:")
                    print("```")
                    print(ds_result.output[:1000])
                    print("```\n")
        explanation = self._generate_step_explanation(step, code)
        print("\nExplanation\n")
        print(explanation)
        if step.leads_to:
            print(f"\nNext: {step.leads_to}")

    def _get_step_code(self, step: WalkStep) -> str:
        file_path, start_hint, end_hint = self._split_path_and_line_info(
            step.file_path
        )
        if file_path != step.file_path:
            self._log_debug(
                f"Normalized file path from '{step.file_path}' to '{file_path}'"
            )
        start_line = step.start_line or start_hint
        end_line = step.end_line or end_hint

        resolved_path = self._resolve_missing_path(file_path)
        if resolved_path and resolved_path != file_path:
            self._log_debug(
                f"Resolved missing path '{file_path}' to '{resolved_path}'"
            )
            file_path = resolved_path

        if self._path_is_dir(file_path):
            self._log_warning(
                f"Step file_path '{file_path}' is a directory; attempting symbol-based resolution."
            )
            symbol = self._extract_symbol(step.function_or_section) if step.function_or_section else ""
            if symbol:
                match = self._find_definition_in_path(symbol, file_path)
                if match:
                    match_path, match_line = match
                    self._log_debug(
                        f"Resolved directory '{file_path}' using symbol '{symbol}' to '{match_path}'."
                    )
                    file_path = match_path
                    start_line = start_line or match_line
                else:
                    self._log_warning(
                        f"No definition match found for symbol '{symbol}' under '{file_path}'."
                    )
            else:
                self._log_warning(
                    f"No function_or_section provided for directory '{file_path}'."
                )

        last_error: Optional[str] = None
        if step.function_or_section:
            symbol = self._extract_symbol(step.function_or_section)
            result = self.tools.get_function(file_path, symbol)
            if not result.success:
                last_error = f"get_function failed: {result.error}"
                result = self.tools.get_class(file_path, symbol)
            if result.success:
                return result.output
            last_error = f"get_class failed: {result.error}"
        if start_line or end_line:
            result = self.tools.read_file(
                file_path, start_line=start_line, end_line=end_line
            )
            if result.success:
                return result.output
            last_error = f"read_file range failed: {result.error}"
        result = self.tools.read_file(file_path)
        if result.success:
            return result.output
        last_error = f"read_file failed: {result.error}"
        self._log_warning(
            f"Could not retrieve code for '{file_path}'. {last_error}"
        )
        return "(Could not retrieve code)"

    def _generate_step_explanation(self, step: WalkStep, code: str) -> str:
        prompt = build_step_explanation_prompt(
            user_request=self.state.user_request,
            step_data={
                "title": step.title,
                "why_important": step.why_important,
                "key_concepts": step.key_concepts,
            },
            code=code,
        )
        messages = [{"role": "user", "content": prompt}]
        return self.client.generate(messages, max_output_tokens=1500)

    # ===== Parsing Helpers =====

    def _parse_json(self, text: str) -> Optional[Dict]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```", 2)
            if len(parts) >= 2:
                cleaned = parts[1]
                if cleaned.strip().startswith("json"):
                    cleaned = cleaned.strip()[4:]
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    return None
        return None

    def _coerce_int(self, value: Optional[object]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_symbol(self, text: str) -> str:
        cleaned = text.strip()
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].strip()
        if "(" in cleaned:
            cleaned = cleaned.split("(", 1)[0].strip()
        if " " in cleaned:
            cleaned = cleaned.split()[-1].strip()
        return cleaned

    def _is_redundant_action(self, action: Dict) -> bool:
        if not action or action.get("type") != "tool":
            return False
        if not self.state.tool_calls:
            return False
        last = self.state.tool_calls[-1]
        return action.get("tool") == last.get("tool") and action.get("args") == last.get(
            "args"
        )

    def _build_repeat_warning(self, action: Dict) -> str:
        if not self.state.tool_calls:
            return "Avoid repeating the same tool."
        last = self.state.tool_calls[-1]
        tool = last.get("tool")
        args = last.get("args")
        return (
            f"You just ran {tool} with {args}. Do not repeat it; choose a different "
            "tool or respond with done."
        )

    def _split_path_and_line_info(
        self, file_path: str
    ) -> tuple[str, Optional[int], Optional[int]]:
        cleaned = self._clean_file_path(file_path)

        hash_match = re.search(r"#L(\d+)(?:-L?(\d+))?$", cleaned)
        if hash_match:
            start = int(hash_match.group(1))
            end = int(hash_match.group(2)) if hash_match.group(2) else None
            return cleaned[: hash_match.start()].strip(), start, end

        paren_match = re.search(
            r"\s*[\(\[]\s*line\s*(\d+)(?:\s*-\s*(\d+))?\s*[\)\]]\s*$",
            cleaned,
            re.IGNORECASE,
        )
        if paren_match:
            start = int(paren_match.group(1))
            end = int(paren_match.group(2)) if paren_match.group(2) else None
            return cleaned[: paren_match.start()].strip(), start, end

        if ":" in cleaned and not re.match(r"^[A-Za-z]:[\\/]", cleaned):
            range_match = re.search(r":(\d+)-(\d+)$", cleaned)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2))
                return cleaned[: range_match.start()].strip(), start, end

            colon_match = re.search(r":(\d+)(?::\d+)?$", cleaned)
            if colon_match:
                start = int(colon_match.group(1))
                return cleaned[: colon_match.start()].strip(), start, None

        return cleaned, None, None

    def _clean_file_path(self, file_path: str) -> str:
        cleaned = file_path.strip().strip('"').strip("'")
        if cleaned.startswith("file://"):
            cleaned = cleaned[7:]
        cleaned = os.path.expandvars(os.path.expanduser(cleaned))
        return cleaned.strip()

    def _path_exists(self, path: str) -> bool:
        try:
            return self.tools._resolve_path(path).exists()
        except Exception:
            return False

    def _resolve_missing_path(self, path: str) -> Optional[str]:
        if not path:
            return None
        if self._path_exists(path):
            return path
        basename = Path(path).name
        if not basename:
            return None
        result = self.tools.find_files(basename)
        if not result.success or result.output in ("(no matches)", "(empty output)"):
            return None
        matches = [line.strip() for line in result.output.splitlines() if line.strip()]
        if len(matches) == 1:
            return matches[0]
        self._log_debug(f"Multiple matches for '{basename}': {matches[:5]}")
        return None

    def _find_definition_in_path(
        self, symbol: str, search_path: str
    ) -> Optional[tuple[str, int]]:
        patterns = self._definition_patterns(symbol)
        for pattern in patterns:
            result = self.tools.grep(
                pattern, path=search_path, context_lines=0, ignore_case=False
            )
            if not result.success or result.output in ("(no matches)", "(empty output)", ""):
                continue
            match = self._parse_grep_first_match(result.output)
            if match:
                return match
        return None

    def _definition_patterns(self, symbol: str) -> List[str]:
        sym = re.escape(symbol)
        return [
            rf"\bdef\s+{sym}\s*\(",
            rf"\bclass\s+{sym}\b",
            rf"^{sym}\s*=",
            rf"\bfunc\s+{sym}\s*\(",
            rf"\bfunc\s+\([^)]+\)\s+{sym}\s*\(",
            rf"\btype\s+{sym}\b",
            rf"\bfn\s+{sym}\s*\(",
            rf"\bstruct\s+{sym}\b",
            rf"\benum\s+{sym}\b",
            rf"\bimpl\s+{sym}\b",
            rf"\bfunction\s+{sym}\s*\(",
            rf"\bconst\s+{sym}\s*=",
            rf"\binterface\s+{sym}\b",
        ]

    def _parse_grep_first_match(self, output: str) -> Optional[tuple[str, int]]:
        for line in output.splitlines():
            if not line or line.startswith("--"):
                continue
            match = re.match(r"^(.*?):(\d+):", line)
            if match:
                path = match.group(1)
                try:
                    line_number = int(match.group(2))
                except ValueError:
                    continue
                return path, line_number
        return None

    def _log_debug(self, message: str) -> None:
        if self.verbose:
            print(f"[debug] {message}")

    def _log_warning(self, message: str) -> None:
        print(f"[warn] {message}")

    def _path_is_dir(self, path: str) -> bool:
        try:
            return self.tools._resolve_path(path).is_dir()
        except Exception:
            return False
