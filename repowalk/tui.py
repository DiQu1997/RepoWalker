from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import json
import os
import re
import sys
import select
import termios
import textwrap
import tty

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.segment import Segment
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .repo_scout.agent import CodeWalkerAgent


@dataclass
class UIStep:
    step_number: int
    title: str
    file_path: str
    start_line: int
    code: str
    explanation: str
    data_structures: List[Dict[str, str]] = field(default_factory=list)
    key_concepts: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    leads_to: Optional[str] = None


@dataclass
class WalkSession:
    title: str
    overview: str
    steps: List[UIStep]
    current_step: int = 0
    dive_stack: List[Tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class SearchResult:
    label: str
    kind: str
    step_index: Optional[int] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    preview: Optional[str] = None


def build_session(agent: CodeWalkerAgent, user_request: str) -> WalkSession:
    plan = agent.prepare_plan(user_request)
    if not plan or not plan.steps:
        raise RuntimeError("No plan available to build a TUI session.")

    steps: List[UIStep] = []
    for step in plan.steps:
        normalized_path, hint_start, _ = _normalize_file_path(step.file_path)
        if normalized_path != step.file_path:
            step.file_path = normalized_path

        code_with_numbers = agent.get_step_code(step)
        cleaned_code, inferred_start = _strip_line_numbers(code_with_numbers)
        start_line = step.start_line or hint_start or inferred_start or 1
        explanation = agent.generate_step_explanation(step, cleaned_code)
        data_structures = _resolve_data_structures(agent, step.data_structures)
        calls = _extract_calls(cleaned_code)

        steps.append(
            UIStep(
                step_number=step.step_number,
                title=step.title,
                file_path=step.file_path,
                start_line=start_line,
                code=cleaned_code,
                explanation=explanation,
                data_structures=data_structures,
                key_concepts=step.key_concepts,
                calls=calls,
                leads_to=step.leads_to,
            )
        )

    return WalkSession(title=plan.title, overview=plan.overview, steps=steps)


def run_tui(session: WalkSession, agent: CodeWalkerAgent, debug: bool = False) -> None:
    tui = CodeWalkerTUI(session=session, agent=agent, debug=debug)
    tui.run()


def _strip_line_numbers(code: str) -> Tuple[str, Optional[int]]:
    lines = code.splitlines()
    start_line: Optional[int] = None
    cleaned_lines: List[str] = []
    for line in lines:
        match = re.match(r"\s*(\d+)\s*\|\s?(.*)$", line)
        if match:
            if start_line is None:
                start_line = int(match.group(1))
            cleaned_lines.append(match.group(2))
        else:
            cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).rstrip()
    return cleaned, start_line


def _normalize_file_path(path: str) -> Tuple[str, Optional[int], Optional[int]]:
    cleaned = path.strip().strip('"').strip("'")
    if cleaned.startswith("file://"):
        cleaned = cleaned[7:]
    cleaned = os.path.expandvars(os.path.expanduser(cleaned))

    hash_match = re.search(r"#L(\d+)(?:-L?(\d+))?$", cleaned)
    if hash_match:
        start = int(hash_match.group(1))
        end = int(hash_match.group(2)) if hash_match.group(2) else None
        return cleaned[: hash_match.start()].strip(), start, end

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


def _resolve_data_structures(
    agent: CodeWalkerAgent, names: List[str]
) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for name in names:
        definition = ""
        found = agent.tools.find_definition(name)
        if found.success and found.output != f"No definition found for: {name}":
            definition = found.output
        else:
            definition = "Definition not found."
        results.append({"name": name, "definition": definition})
    return results


def _extract_calls(code: str) -> List[str]:
    if not code:
        return []
    keywords = {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "catch",
        "def",
        "class",
        "func",
        "fn",
        "sizeof",
        "new",
    }
    calls: List[str] = []
    seen = set()
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_:]*)\s*\(", code):
        name = match.group(1)
        if name in keywords:
            continue
        if name not in seen:
            seen.add(name)
            calls.append(name)
        if len(calls) >= 12:
            break
    return calls


class CodeWalkerTUI:
    def __init__(self, session: WalkSession, agent: CodeWalkerAgent, debug: bool = False):
        self.session = session
        self.agent = agent
        self.console = Console()
        self.debug = debug
        self.focus = "code"
        self.view_mode = "split"
        self.data_structures_expanded = False
        self.show_breadcrumb = True
        self.split_ratio = 0.5
        self.code_scroll = 0
        self.code_cursor = 0
        self.explain_scroll = 0
        self.status_message = ""
        self.overlay_title: Optional[str] = None
        self.overlay_lines: List[str] = []
        self.overlay_scroll = 0
        self.search_active = False
        self.search_query = ""
        self.search_results: List[SearchResult] = []
        self.search_selected = 0
        self.last_key = ""

    def run(self) -> None:
        with Live(self.render(), console=self.console, refresh_per_second=10, screen=True) as live:
            while True:
                key = self._get_key()
                if not key:
                    continue
                if key in ("q", "\x03"):
                    break
                handled = self._handle_key(key)
                if handled == "quit":
                    break
                live.update(self.render())

    # ===== Rendering =====

    def render(self) -> Layout:
        layout = Layout()
        header_height = 3
        footer_height = 3
        data_height = 6 if self.data_structures_expanded else 3
        breadcrumb_height = 3 if self.show_breadcrumb else 0

        layout.split_column(
            Layout(name="header", size=header_height),
            Layout(name="main", ratio=1),
            Layout(name="data", size=data_height),
            Layout(name="breadcrumb", size=breadcrumb_height),
            Layout(name="footer", size=footer_height),
        )

        layout["header"].update(self._render_header())

        main_height = max(
            5,
            self.console.size.height
            - header_height
            - data_height
            - breadcrumb_height
            - footer_height,
        )
        main_width = self.console.size.width

        if self.search_active:
            layout["main"].update(self._render_search_overlay(main_height, main_width))
        elif self.overlay_title:
            layout["main"].update(self._render_overlay(main_height, main_width))
        else:
            self._render_main(layout["main"], main_height, main_width)

        if not self.search_active and not self.overlay_title:
            layout["data"].update(self._render_data_structures(data_height))
        else:
            layout["data"].update(Panel(Text(""), border_style="cyan"))

        if self.show_breadcrumb and not self.search_active and not self.overlay_title:
            layout["breadcrumb"].update(self._render_breadcrumb())
        else:
            layout["breadcrumb"].update(Panel(Text(""), border_style="yellow"))

        layout["footer"].update(self._render_footer())
        return layout

    def _render_main(self, main_layout: Layout, height: int, width: int) -> None:
        if self.view_mode == "overview":
            main_layout.update(self._render_overview(height, width))
            return

        if self.view_mode == "code":
            main_layout.update(self._render_code_panel(height, width))
            return

        if self.view_mode == "explanation":
            main_layout.update(self._render_explanation_panel(height, width, width))
            return

        min_code = 20
        min_explain = 20
        if width < min_code + min_explain:
            min_code = max(10, width // 2)
            min_explain = max(10, width - min_code)
        code_width = int(width * self.split_ratio)
        code_width = max(min_code, min(code_width, width - min_explain))
        explain_width = max(5, width - code_width)
        main_layout.split_row(
            Layout(name="code", size=code_width),
            Layout(name="explanation", ratio=1),
        )
        main_layout["code"].update(self._render_code_panel(height, code_width))
        main_layout["explanation"].update(
            self._render_explanation_panel(height, width, explain_width)
        )

    def _render_header(self) -> Panel:
        step = self._current_step()
        title = Text()
        title.append("Code Walker", style="bold cyan")
        title.append("  |  ", style="dim")
        title.append(
            f"Step {self.session.current_step + 1}/{len(self.session.steps)}",
            style="bold yellow",
        )
        title.append("  |  ", style="dim")
        title.append(step.file_path, style="green")
        max_width = max(10, self.console.size.width - 4)
        title.truncate(max_width, overflow="ellipsis")
        return Panel(title, style="bold")

    def _render_code_panel(self, height: int, width: int) -> Panel:
        step = self._current_step()
        code_lines = step.code.splitlines() or ["(no code)"]
        visible_height = max(3, height - 2)
        self._clamp_code_scroll(len(code_lines), visible_height)
        visible_lines = code_lines[self.code_scroll : self.code_scroll + visible_height]

        start_line = step.start_line + self.code_scroll
        highlight_line = step.start_line + self.code_cursor
        highlight_lines = {highlight_line} if self._cursor_visible(visible_height) else set()

        syntax = Syntax(
            "\n".join(visible_lines),
            self._detect_language(step.file_path),
            theme="ansi_dark",
            line_numbers=True,
            start_line=start_line,
            highlight_lines=highlight_lines,
            word_wrap=False,
            background_color="default",
        )

        border_style = "bold green" if self.focus == "code" else "green"
        return Panel(
            syntax,
            title=step.title,
            border_style=border_style,
            padding=(0, 1),
        )

    def _render_explanation_panel(
        self, height: int, width: int, panel_width: int
    ) -> Panel:
        step = self._current_step()
        content_width = max(20, panel_width - 6)
        lines = self._format_explanation_lines(step, content_width)
        visible_height = max(3, height - 2)
        self._clamp_explain_scroll(len(lines), visible_height)
        visible_lines = lines[self.explain_scroll : self.explain_scroll + visible_height]

        text = Text()
        for idx, line in enumerate(visible_lines):
            if idx:
                text.append("\n")
            if isinstance(line, Text):
                text.append_text(line)
            else:
                text.append(str(line))
        border_style = "bold blue" if self.focus == "explanation" else "blue"
        return Panel(
            text,
            title="Explanation",
            border_style=border_style,
            padding=(0, 1),
        )

    def _render_data_structures(self, height: int) -> Panel:
        step = self._current_step()
        if not step.data_structures:
            return Panel(
                Text("No data structures for this step", style="dim"),
                title="Data Structures",
                border_style="cyan",
                height=height,
            )
        if not self.data_structures_expanded:
            names = [s.get("name", "?") for s in step.data_structures]
            return Panel(
                Text(f"Data Structures: {', '.join(names)}", style="cyan"),
                border_style="cyan",
                height=height,
            )

        table = Table(show_header=False, box=None, padding=(0, 1))
        for struct in step.data_structures:
            name = struct.get("name", "")
            definition_lines = struct.get("definition", "").splitlines()
            definition = definition_lines[0] if definition_lines else ""
            table.add_row(Text(name, style="bold cyan"), Text(definition, style="dim"))

        return Panel(
            table,
            title="Data Structures [d to collapse]",
            border_style="cyan",
            height=height,
        )

    def _render_breadcrumb(self) -> Panel:
        parts = []
        for i, step in enumerate(self.session.steps):
            name = step.title.split(":")[-1].strip()[:15]
            if i == self.session.current_step:
                parts.append(f"[bold reverse cyan] {name} [/]")
            else:
                parts.append(f"[dim]{name}[/]")
        path_text = " -> ".join(parts)
        text = Text.from_markup(f"Path: {path_text}")
        max_width = max(10, self.console.size.width - 4)
        text.truncate(max_width, overflow="ellipsis")
        return Panel(text, border_style="yellow")

    def _render_footer(self) -> Panel:
        shortcuts = Text()
        shortcuts.append(" [<-] ", style="bold")
        shortcuts.append("Prev  ", style="dim")
        shortcuts.append("[->] ", style="bold")
        shortcuts.append("Next  ", style="dim")
        shortcuts.append("[Tab] ", style="bold")
        shortcuts.append("Focus  ", style="dim")
        shortcuts.append("[d] ", style="bold")
        shortcuts.append("Data  ", style="dim")
        shortcuts.append("[/] ", style="bold")
        shortcuts.append("Search  ", style="dim")
        shortcuts.append("[q] ", style="bold")
        shortcuts.append("Quit", style="dim")

        if self.status_message:
            shortcuts.append("  |  ", style="dim")
            shortcuts.append(self.status_message, style="yellow")
        if self.debug:
            shortcuts.append("  |  ", style="dim")
            shortcuts.append(
                f"focus={self.focus} view={self.view_mode} key={self.last_key}",
                style="dim",
            )
        max_width = max(10, self.console.size.width - 4)
        shortcuts.truncate(max_width, overflow="ellipsis")

        return Panel(shortcuts, style="dim")

    def _render_overview(self, height: int, width: int) -> Panel:
        names = [step.title.split(":")[-1].strip() for step in self.session.steps]
        path_text = " -> ".join(names)
        wrapped = textwrap.wrap(path_text, width=max(20, width - 6))
        text = Text("\n".join(wrapped))
        return Panel(text, title="Overview", border_style="magenta", height=height)

    def _render_overlay(self, height: int, width: int) -> Panel:
        visible_height = max(3, height - 2)
        self._clamp_overlay_scroll(len(self.overlay_lines), visible_height)
        visible_lines = self.overlay_lines[
            self.overlay_scroll : self.overlay_scroll + visible_height
        ]
        text = Text("\n".join(visible_lines))
        return Panel(
            text,
            title=self.overlay_title or "Info",
            border_style="bright_cyan",
            height=height,
        )

    def _render_search_overlay(self, height: int, width: int) -> Panel:
        lines = [f"Search: {self.search_query}", ""]
        if not self.search_results:
            lines.append("No results")
        else:
            for idx, result in enumerate(self.search_results[:20]):
                prefix = "> " if idx == self.search_selected else "  "
                lines.append(f"{prefix}{result.label}")
        text = Text("\n".join(lines))
        return Panel(text, title="Find Symbol", border_style="bright_cyan", height=height)

    # ===== Input Handling =====

    def _handle_key(self, key: str) -> Optional[str]:
        key = self._normalize_key(key)
        self.last_key = key
        if self.search_active:
            return self._handle_search_key(key)
        if self.overlay_title:
            return self._handle_overlay_key(key)

        if key in ("h", "LEFT"):
            self._prev_step()
        elif key in ("l", "RIGHT"):
            self._next_step()
        elif key in ("k", "UP"):
            self._scroll_up()
        elif key in ("j", "DOWN"):
            self._scroll_down()
        elif key in ("ESC", "MOUSE"):
            return None
        elif key == "g":
            self._go_to_step(0)
        elif key == "G":
            self._go_to_step(len(self.session.steps) - 1)
        elif key == "\t":
            self._toggle_focus()
        elif key == "d":
            self.data_structures_expanded = not self.data_structures_expanded
        elif key == "p":
            self.show_breadcrumb = not self.show_breadcrumb
        elif key == "1":
            self.view_mode = "split"
        elif key == "2":
            self.view_mode = "code"
        elif key == "3":
            self.view_mode = "explanation"
        elif key in ("4", "o"):
            self.view_mode = "overview"
        elif key == "+":
            self.split_ratio = min(0.8, self.split_ratio + 0.05)
        elif key == "-":
            self.split_ratio = max(0.2, self.split_ratio - 0.05)
        elif key == "/":
            self._open_search()
        elif key == "\r":
            self._dive_into_symbol()
        elif key in ("\x7f", "\b"):
            self._go_back()
        elif key == "r":
            self._go_to_step(0)
        elif key == "s":
            self._save_session()
        elif key == "\x05":
            self._export_markdown()
        elif key == "i":
            self._show_file_info()
        elif key == "c":
            self._show_git_blame()
        elif key == "f":
            self._show_usages()
        elif key == "t":
            self._show_definition()
        elif key == "?":
            self._show_help()
        return None

    def _handle_search_key(self, key: str) -> Optional[str]:
        if key in ("ESC", "MOUSE"):
            self.search_active = False
            self.search_query = ""
            self.search_results = []
            return None
        if key in ("\r", "\n"):
            if self.search_results:
                self._activate_search_result()
            else:
                self.search_active = False
            return None
        if key in ("\x7f", "\b"):
            self.search_query = self.search_query[:-1]
        elif key in ("UP", "k"):
            self.search_selected = max(0, self.search_selected - 1)
            return None
        elif key in ("DOWN", "j"):
            self.search_selected = min(
                len(self.search_results) - 1, self.search_selected + 1
            )
            return None
        elif len(key) == 1 and key.isprintable():
            self.search_query += key
        self._perform_search()
        return None

    def _handle_overlay_key(self, key: str) -> Optional[str]:
        if key in ("ESC", "MOUSE", "q"):
            self._clear_overlay()
            return None
        if key in ("UP", "k"):
            self.overlay_scroll = max(0, self.overlay_scroll - 1)
        elif key in ("DOWN", "j"):
            self.overlay_scroll = min(
                max(0, len(self.overlay_lines) - 1), self.overlay_scroll + 1
            )
        return None

    # ===== Actions =====

    def _prev_step(self) -> None:
        if self.session.current_step > 0:
            self._go_to_step(self.session.current_step - 1)

    def _next_step(self) -> None:
        if self.session.current_step < len(self.session.steps) - 1:
            self._go_to_step(self.session.current_step + 1)

    def _go_to_step(self, index: int) -> None:
        self.session.current_step = index
        self.code_scroll = 0
        self.code_cursor = 0
        self.explain_scroll = 0
        self.status_message = ""

    def _toggle_focus(self) -> None:
        self.focus = "explanation" if self.focus == "code" else "code"

    def _scroll_up(self) -> None:
        if self.focus == "code":
            if self.code_cursor > 0:
                self.code_cursor -= 1
        else:
            self.explain_scroll = max(0, self.explain_scroll - 1)

    def _scroll_down(self) -> None:
        if self.focus == "code":
            code_lines = self._current_step().code.splitlines()
            if self.code_cursor < max(0, len(code_lines) - 1):
                self.code_cursor += 1
        else:
            self.explain_scroll += 1

    def _open_search(self) -> None:
        self.search_active = True
        self.search_query = ""
        self.search_results = []
        self.search_selected = 0

    def _activate_search_result(self) -> None:
        result = self.search_results[self.search_selected]
        self.search_active = False
        if result.kind == "step" and result.step_index is not None:
            self._go_to_step(result.step_index)
            return
        if result.kind in ("definition", "usage") and result.file_path:
            self._show_snippet(result.file_path, result.line_number, result.preview)
            return
        self.status_message = "No action for result"

    def _dive_into_symbol(self) -> None:
        symbol = self._symbol_at_cursor()
        if not symbol:
            self.status_message = "No symbol on current line"
            return
        target = self._find_step_by_symbol(symbol)
        if target is not None:
            self.session.dive_stack.append(
                (self.session.current_step, self.code_cursor, self.code_scroll, self.explain_scroll)
            )
            self._go_to_step(target)
            return
        self._show_definition_for_symbol(symbol)

    def _go_back(self) -> None:
        if not self.session.dive_stack:
            self.status_message = "Already at root"
            return
        step_idx, cursor, code_scroll, explain_scroll = self.session.dive_stack.pop()
        self.session.current_step = step_idx
        self.code_cursor = cursor
        self.code_scroll = code_scroll
        self.explain_scroll = explain_scroll

    def _show_definition(self) -> None:
        symbol = self._symbol_at_cursor()
        if not symbol:
            self.status_message = "No symbol on current line"
            return
        self._show_definition_for_symbol(symbol)

    def _show_definition_for_symbol(self, symbol: str) -> None:
        result = self.agent.tools.find_definition(symbol)
        if result.success:
            self._set_overlay(
                f"Definition: {symbol}", result.output.splitlines() or ["No output"]
            )
        else:
            self._set_overlay(f"Definition: {symbol}", [result.error or "Error"])

    def _show_usages(self) -> None:
        symbol = self._symbol_at_cursor()
        if not symbol:
            self.status_message = "No symbol on current line"
            return
        result = self.agent.tools.find_usages(symbol)
        if result.success:
            self._set_overlay(f"Usages: {symbol}", result.output.splitlines())
        else:
            self._set_overlay(f"Usages: {symbol}", [result.error or "Error"])

    def _show_file_info(self) -> None:
        step = self._current_step()
        result = self.agent.tools.file_info(step.file_path)
        if result.success:
            self._set_overlay("File Info", result.output.splitlines())
        else:
            self._set_overlay("File Info", [result.error or "Error"])

    def _show_git_blame(self) -> None:
        step = self._current_step()
        line_number = step.start_line + self.code_cursor
        result = self.agent.tools.git_blame(step.file_path, line_number, line_number)
        if result.success:
            self._set_overlay("Git Blame", result.output.splitlines())
        else:
            self._set_overlay("Git Blame", [result.error or "Error"])

    def _show_snippet(
        self, file_path: str, line_number: Optional[int], preview: Optional[str]
    ) -> None:
        if line_number:
            start = max(1, line_number - 4)
            end = line_number + 4
            result = self.agent.tools.read_file(file_path, start, end)
            if result.success:
                self._set_overlay("Snippet", result.output.splitlines())
                return
        if preview:
            self._set_overlay("Snippet", [preview])
            return
        self._set_overlay("Snippet", ["No preview available"])

    def _show_help(self) -> None:
        lines = [
            "Navigation:",
            "  Left/Right or h/l  - Prev/Next step",
            "  Up/Down or k/j     - Scroll focused panel",
            "  g/G                - First/Last step",
            "",
            "View:",
            "  Tab                - Toggle focus",
            "  1/2/3/4 or o        - View modes",
            "  +/-                - Adjust split ratio",
            "  d                  - Toggle data structures",
            "  p                  - Toggle path breadcrumb",
            "",
            "Explore:",
            "  /                  - Search symbols",
            "  Enter              - Dive into symbol",
            "  Backspace          - Go back",
            "  f/t                - Find usages / definition",
            "  i/c                - File info / git blame",
            "",
            "General:",
            "  s                  - Save session",
            "  Ctrl+e             - Export markdown",
            "  q                  - Quit",
            "  Esc                - Close overlays",
        ]
        self._set_overlay("Help", lines)

    def _save_session(self) -> None:
        path = Path.cwd() / "repowalk_session.json"
        data = {
            "title": self.session.title,
            "overview": self.session.overview,
            "steps": [asdict(step) for step in self.session.steps],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.status_message = f"Saved {path.name}"

    def _export_markdown(self) -> None:
        path = Path.cwd() / "repowalk_session.md"
        lines = [f"# {self.session.title}", "", self.session.overview, ""]
        for step in self.session.steps:
            lines.append(f"## Step {step.step_number}: {step.title}")
            lines.append(f"File: {step.file_path}")
            lines.append("")
            lines.append("```")
            lines.append(step.code)
            lines.append("```")
            lines.append("")
            lines.append(step.explanation)
            lines.append("")
            if step.data_structures:
                lines.append("Data Structures:")
                for struct in step.data_structures:
                    lines.append(f"- {struct.get('name')}: {struct.get('definition')}")
                lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        self.status_message = f"Exported {path.name}"

    # ===== Helpers =====

    def _current_step(self) -> UIStep:
        return self.session.steps[self.session.current_step]

    def _format_explanation_lines(self, step: UIStep, width: int) -> List[Text]:
        content = [
            f"## {step.title}",
            "",
            step.explanation or "(no explanation available)",
            "",
            f"**Key Concepts:** {', '.join(step.key_concepts) if step.key_concepts else 'None'}",
            f"**Calls:** {', '.join(step.calls) if step.calls else 'None'}",
        ]
        markdown = Markdown("\n".join(content))
        render_console = Console(
            width=width,
            color_system=self.console.color_system,
            force_terminal=True,
        )
        rendered_lines = render_console.render_lines(markdown)
        lines: List[Text] = []
        for line in rendered_lines:
            if not line:
                lines.append(Text(""))
                continue
            segments = [(seg.text, seg.style) for seg in line if isinstance(seg, Segment)]
            if not segments:
                lines.append(Text(""))
                continue
            lines.append(Text.assemble(*segments))
        return lines

    def _symbol_at_cursor(self) -> Optional[str]:
        step = self._current_step()
        code_lines = step.code.splitlines()
        if not code_lines or self.code_cursor >= len(code_lines):
            return None
        line = code_lines[self.code_cursor]
        match = re.search(r"([A-Za-z_][A-Za-z0-9_:]*)\s*\(", line)
        if match:
            return match.group(1)
        match = re.search(r"\b([A-Za-z_][A-Za-z0-9_:]*)\b", line)
        if match:
            return match.group(1)
        return None

    def _find_step_by_symbol(self, symbol: str) -> Optional[int]:
        symbol_lower = symbol.lower()
        for idx, step in enumerate(self.session.steps):
            if symbol_lower in step.title.lower():
                return idx
        return None

    def _perform_search(self) -> None:
        query = self.search_query.strip()
        results: List[SearchResult] = []
        if query:
            query_lower = query.lower()
            for idx, step in enumerate(self.session.steps):
                if (
                    query_lower in step.title.lower()
                    or query_lower in step.file_path.lower()
                    or query_lower in step.code.lower()
                ):
                    results.append(
                        SearchResult(
                            label=f"Step {step.step_number}: {step.title}",
                            kind="step",
                            step_index=idx,
                        )
                    )
            if re.match(r"^[A-Za-z_][A-Za-z0-9_:]*$", query):
                result = self.agent.tools.find_definition(query)
                if result.success:
                    results.extend(self._parse_definition_results(query, result.output))
        self.search_results = results
        self.search_selected = 0

    def _parse_definition_results(
        self, symbol: str, output: str
    ) -> List[SearchResult]:
        results: List[SearchResult] = []
        for line in output.splitlines():
            if not line or line.startswith("---"):
                continue
            match = re.match(r"^(.*?):(\d+):\s*(.*)$", line)
            if not match:
                continue
            file_path = match.group(1)
            line_number = int(match.group(2))
            preview = match.group(3).strip()
            label = f"{symbol}  {file_path}:{line_number}"
            results.append(
                SearchResult(
                    label=label,
                    kind="definition",
                    file_path=file_path,
                    line_number=line_number,
                    preview=preview,
                )
            )
        return results

    def _detect_language(self, file_path: str) -> str:
        ext_map = {
            ".py": "python",
            ".go": "go",
            ".rs": "rust",
            ".js": "javascript",
            ".ts": "typescript",
            ".cc": "cpp",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "cpp",
            ".java": "java",
            ".rb": "ruby",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return "text"

    def _get_key(self) -> str:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = ch
                while True:
                    ready, _, _ = select.select([sys.stdin], [], [], 0.02)
                    if not ready:
                        break
                    nxt = sys.stdin.read(1)
                    seq += nxt
                    if nxt.isalpha() or nxt == "~":
                        break
                    if len(seq) >= 12:
                        break
                return seq
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _normalize_key(self, key: str) -> str:
        if key.startswith("\x1b[") or key.startswith("\x1bO"):
            last = key[-1]
            if last == "A":
                return "UP"
            if last == "B":
                return "DOWN"
            if last == "C":
                return "RIGHT"
            if last == "D":
                return "LEFT"
            return "ESC"
        if key.startswith("\x1b"):
            if "[<" in key or "M" in key:
                return "MOUSE"
            return "ESC"
        return key

    def _cursor_visible(self, visible_height: int) -> bool:
        return self.code_cursor >= self.code_scroll and self.code_cursor < (
            self.code_scroll + visible_height
        )

    def _clamp_code_scroll(self, total_lines: int, visible_height: int) -> None:
        if total_lines <= visible_height:
            self.code_scroll = 0
            self.code_cursor = min(self.code_cursor, max(0, total_lines - 1))
            return
        if self.code_cursor < self.code_scroll:
            self.code_scroll = self.code_cursor
        if self.code_cursor >= self.code_scroll + visible_height:
            self.code_scroll = self.code_cursor - visible_height + 1
        self.code_scroll = max(0, min(self.code_scroll, total_lines - visible_height))

    def _clamp_explain_scroll(self, total_lines: int, visible_height: int) -> None:
        if total_lines <= visible_height:
            self.explain_scroll = 0
            return
        self.explain_scroll = max(
            0, min(self.explain_scroll, total_lines - visible_height)
        )

    def _clamp_overlay_scroll(self, total_lines: int, visible_height: int) -> None:
        if total_lines <= visible_height:
            self.overlay_scroll = 0
            return
        self.overlay_scroll = max(
            0, min(self.overlay_scroll, total_lines - visible_height)
        )

    def _set_overlay(self, title: str, lines: List[str]) -> None:
        self.overlay_title = title
        self.overlay_lines = lines or ["(empty)"]
        self.overlay_scroll = 0

    def _clear_overlay(self) -> None:
        self.overlay_title = None
        self.overlay_lines = []
        self.overlay_scroll = 0
