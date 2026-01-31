from __future__ import annotations

import curses
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import Token
from pygments.util import ClassNotFound

from ..repo_scout.agent import CodeWalkerAgent
from ..tui import WalkSession, UIStep

COLOR_HEADER = 1
COLOR_BORDER = 2
COLOR_TITLE = 3
COLOR_FOCUS = 4
COLOR_DIM = 5
COLOR_SYNTAX_KEYWORD = 6
COLOR_SYNTAX_STRING = 7
COLOR_SYNTAX_COMMENT = 8
COLOR_SYNTAX_NUMBER = 9


@dataclass
class SearchResult:
    label: str
    kind: str
    step_index: Optional[int] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    preview: Optional[str] = None


@dataclass
class UIState:
    session: WalkSession
    agent: CodeWalkerAgent
    debug: bool = False
    focus: str = "code"
    view_mode: str = "split"
    split_ratio: float = 0.5
    data_structures_expanded: bool = False
    show_breadcrumb: bool = True
    code_scroll: int = 0
    code_cursor: int = 0
    explain_scroll: int = 0
    code_cache: dict = field(default_factory=dict)
    overlay_title: Optional[str] = None
    overlay_lines: List[str] = field(default_factory=list)
    overlay_scroll: int = 0
    search_active: bool = False
    search_query: str = ""
    search_results: List[SearchResult] = field(default_factory=list)
    search_selected: int = 0
    status_message: str = ""
    last_key: str = ""

    def current_step(self) -> UIStep:
        return self.session.steps[self.session.current_step]

    def set_step(self, index: int) -> None:
        self.session.current_step = index
        self.code_scroll = 0
        self.code_cursor = 0
        self.explain_scroll = 0
        self.status_message = ""


def start_terminal_ui(
    session: WalkSession, agent: CodeWalkerAgent, debug: bool = False
) -> None:
    if not _ensure_tty_input():
        print(
            "Error: Interactive UI requires a TTY for input. Run from a terminal.",
            file=sys.stderr,
        )
        sys.exit(1)
    curses.wrapper(lambda stdscr: _run_ui(stdscr, session, agent, debug))


def _run_ui(
    stdscr, session: WalkSession, agent: CodeWalkerAgent, debug: bool
) -> None:
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    _init_colors()

    state = UIState(session=session, agent=agent, debug=debug)

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 12 or width < 50:
            _safe_addstr(
                stdscr,
                0,
                0,
                "Terminal too small. Resize to at least 50x12.",
            )
        else:
            _render_screen(stdscr, state, height, width)

        stdscr.refresh()

        key = stdscr.getch()
        if key == -1:
            continue
        if not _handle_key(state, key):
            break


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_HEADER, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(COLOR_BORDER, curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_TITLE, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_FOCUS, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_DIM, curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_SYNTAX_KEYWORD, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_SYNTAX_STRING, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_SYNTAX_COMMENT, curses.COLOR_BLUE, -1)
    curses.init_pair(COLOR_SYNTAX_NUMBER, curses.COLOR_MAGENTA, -1)


def _render_screen(stdscr, state: UIState, height: int, width: int) -> None:
    header_h = 1
    footer_h = 1
    data_h = 6 if state.data_structures_expanded else 3
    breadcrumb_h = 1 if state.show_breadcrumb else 0
    main_h = height - header_h - data_h - breadcrumb_h - footer_h
    main_y = header_h

    _render_header(stdscr, state, 0, width)

    if state.search_active:
        _render_main(stdscr, state, main_y, main_h, width)
        _render_search_overlay(stdscr, state, height, width)
    elif state.overlay_title:
        _render_main(stdscr, state, main_y, main_h, width)
        _render_overlay(stdscr, state, height, width)
    else:
        _render_main(stdscr, state, main_y, main_h, width)

    data_y = main_y + main_h
    _render_data_structures(stdscr, state, data_y, data_h, width)

    if state.show_breadcrumb:
        breadcrumb_y = data_y + data_h
        _render_breadcrumb(stdscr, state, breadcrumb_y, width)

    _render_footer(stdscr, state, height - 1, width)


def _render_header(stdscr, state: UIState, y: int, width: int) -> None:
    step = state.current_step()
    title = (
        f"Code Walker | Step {state.session.current_step + 1}"
        f"/{len(state.session.steps)} | {step.file_path}"
    )
    _fill_line(stdscr, y, width, curses.color_pair(COLOR_HEADER))
    _safe_addstr(stdscr, y, 0, _truncate(title, width), curses.color_pair(COLOR_HEADER))


def _render_footer(stdscr, state: UIState, y: int, width: int) -> None:
    parts = [
        "[<-] Prev",
        "[->] Next",
        "[Tab] Focus",
        "[d] Data",
        "[/] Search",
        "[q] Quit",
    ]
    if state.status_message:
        parts.append(f"| {state.status_message}")
    if state.debug and state.last_key:
        parts.append(f"| key={state.last_key}")
    line = "  ".join(parts)
    _fill_line(stdscr, y, width, curses.A_DIM)
    _safe_addstr(stdscr, y, 0, _truncate(line, width), curses.A_DIM)


def _render_main(
    stdscr, state: UIState, y: int, height: int, width: int
) -> None:
    if height < 3:
        return
    if state.view_mode == "overview":
        _render_overview(stdscr, state, y, height, width)
        return

    if state.view_mode == "code":
        _render_code_panel(stdscr, state, y, 0, height, width)
        return

    if state.view_mode == "explanation":
        _render_explanation_panel(stdscr, state, y, 0, height, width)
        return

    min_code = 20
    min_explain = 20
    if width < min_code + min_explain:
        min_code = max(10, width // 2)
        min_explain = max(10, width - min_code)
    code_w = int(width * state.split_ratio)
    code_w = max(min_code, min(code_w, width - min_explain))
    explain_w = max(5, width - code_w)

    _render_code_panel(stdscr, state, y, 0, height, code_w)
    _render_explanation_panel(stdscr, state, y, code_w, height, explain_w)


def _render_code_panel(
    stdscr, state: UIState, y: int, x: int, height: int, width: int
) -> None:
    step = state.current_step()
    _draw_box(
        stdscr,
        y,
        x,
        height,
        width,
        title=step.title,
        focused=state.focus == "code",
    )
    code_lines, line_segments = _get_code_render(state, step)
    visible_h = max(1, height - 2)
    _clamp_code_scroll(state, len(code_lines), visible_h)

    line_start = state.code_scroll
    line_end = min(len(code_lines), line_start + visible_h)
    for row, idx in enumerate(range(line_start, line_end)):
        line_no = step.start_line + idx
        prefix = f"{line_no:4d} | "
        segments = line_segments[idx] if idx < len(line_segments) else []
        if not segments:
            segments = [(code_lines[idx], curses.A_NORMAL)]
        rendered_segments = [(prefix, curses.A_DIM)] + segments
        line_attr = curses.A_REVERSE if idx == state.code_cursor else curses.A_NORMAL
        if state.focus == "code" and idx == state.code_cursor:
            line_attr |= curses.A_BOLD
        _render_segments(
            stdscr,
            y + 1 + row,
            x + 1,
            rendered_segments,
            width - 2,
            line_attr,
        )


def _render_explanation_panel(
    stdscr, state: UIState, y: int, x: int, height: int, width: int
) -> None:
    step = state.current_step()
    _draw_box(
        stdscr,
        y,
        x,
        height,
        width,
        title="Explanation",
        focused=state.focus == "explanation",
    )
    content_width = max(10, width - 2)
    lines = _format_explanation(step, content_width)
    visible_h = max(1, height - 2)
    _clamp_explain_scroll(state, len(lines), visible_h)

    line_start = state.explain_scroll
    line_end = min(len(lines), line_start + visible_h)
    for row, idx in enumerate(range(line_start, line_end)):
        text, attr = lines[idx]
        _safe_addstr(
            stdscr,
            y + 1 + row,
            x + 1,
            _truncate(text, width - 2),
            attr,
        )


def _render_data_structures(
    stdscr, state: UIState, y: int, height: int, width: int
) -> None:
    _draw_box(stdscr, y, 0, height, width, title="Data Structures")
    step = state.current_step()
    if not step.data_structures:
        _safe_addstr(
            stdscr,
            y + 1,
            1,
            _truncate("No data structures for this step", width - 2),
            curses.A_DIM,
        )
        return
    if not state.data_structures_expanded:
        names = ", ".join([s.get("name", "?") for s in step.data_structures])
        _safe_addstr(
            stdscr,
            y + 1,
            1,
            _truncate(f"Data Structures: {names}", width - 2),
        )
        return
    row = y + 1
    for struct in step.data_structures:
        if row >= y + height - 1:
            break
        name = struct.get("name", "Unknown")
        definition = struct.get("definition", "")
        first_line = definition.splitlines()[0] if definition else ""
        line = f"{name}: {first_line}"
        _safe_addstr(stdscr, row, 1, _truncate(line, width - 2))
        row += 1


def _render_breadcrumb(stdscr, state: UIState, y: int, width: int) -> None:
    parts = []
    for idx, step in enumerate(state.session.steps):
        name = step.title.split(":")[-1].strip()[:15]
        if idx == state.session.current_step:
            parts.append(f"[{name}]")
        else:
            parts.append(name)
    line = " -> ".join(parts)
    _fill_line(stdscr, y, width, curses.A_DIM)
    _safe_addstr(stdscr, y, 0, _truncate(f"Path: {line}", width))


def _render_overview(
    stdscr, state: UIState, y: int, height: int, width: int
) -> None:
    _draw_box(stdscr, y, 0, height, width, title="Overview")
    row = y + 1
    max_row = y + height - 1
    content_width = max(10, width - 2)

    def add_wrapped(line: str, attr: int = curses.A_NORMAL) -> None:
        nonlocal row
        if row >= max_row:
            return
        wrapped = textwrap.wrap(line, width=content_width) or [line]
        for item in wrapped:
            if row >= max_row:
                break
            _safe_addstr(stdscr, row, 1, _truncate(item, content_width), attr)
            row += 1

    summary = state.session.overview_summary or state.session.overview or ""
    if summary:
        add_wrapped(summary)
        row += 1

    if state.session.overview_data_flow:
        add_wrapped("Data Flow:", curses.A_BOLD)
        for item in state.session.overview_data_flow:
            add_wrapped(f"- {item}")
        row += 1

    if state.session.overview_flow:
        add_wrapped("Flow:", curses.A_BOLD)
        for flow_line in state.session.overview_flow.splitlines():
            if row >= max_row:
                break
            _safe_addstr(
                stdscr, row, 1, _truncate(flow_line, content_width), curses.A_DIM
            )
            row += 1
        row += 1

    if row < max_row:
        add_wrapped("Steps:", curses.A_BOLD)
        for idx, step in enumerate(state.session.steps):
            if row >= max_row:
                break
            marker = ">" if idx == state.session.current_step else " "
            line = f"{marker} {idx + 1}. {step.title}"
            add_wrapped(line)


def _render_overlay(stdscr, state: UIState, height: int, width: int) -> None:
    box_w = max(30, int(width * 0.7))
    box_h = max(8, int(height * 0.6))
    box_x = (width - box_w) // 2
    box_y = (height - box_h) // 2

    _draw_box(stdscr, box_y, box_x, box_h, box_w, title=state.overlay_title or "Info")
    visible_h = box_h - 2
    _clamp_overlay_scroll(state, len(state.overlay_lines), visible_h)
    start = state.overlay_scroll
    end = min(len(state.overlay_lines), start + visible_h)
    for row, idx in enumerate(range(start, end)):
        _safe_addstr(
            stdscr,
            box_y + 1 + row,
            box_x + 1,
            _truncate(state.overlay_lines[idx], box_w - 2),
        )


def _render_search_overlay(stdscr, state: UIState, height: int, width: int) -> None:
    box_w = max(30, int(width * 0.7))
    box_h = max(8, int(height * 0.6))
    box_x = (width - box_w) // 2
    box_y = (height - box_h) // 2

    _draw_box(stdscr, box_y, box_x, box_h, box_w, title="Find Symbol")
    _safe_addstr(
        stdscr,
        box_y + 1,
        box_x + 1,
        _truncate(f"Search: {state.search_query}", box_w - 2),
    )
    row = box_y + 3
    for idx, result in enumerate(state.search_results[: box_h - 4]):
        prefix = "> " if idx == state.search_selected else "  "
        line = prefix + result.label
        attr = curses.A_REVERSE if idx == state.search_selected else curses.A_NORMAL
        _safe_addstr(
            stdscr, row, box_x + 1, _truncate(line, box_w - 2), attr
        )
        row += 1


def _handle_key(state: UIState, key: int) -> bool:
    state.last_key = _key_name(key)

    if key == ord("q"):
        return False

    if state.search_active:
        _handle_search_key(state, key)
        return True

    if state.overlay_title:
        _handle_overlay_key(state, key)
        return True

    if key in (curses.KEY_LEFT, ord("h")):
        if state.session.current_step > 0:
            state.set_step(state.session.current_step - 1)
    elif key in (curses.KEY_RIGHT, ord("l")):
        if state.session.current_step < len(state.session.steps) - 1:
            state.set_step(state.session.current_step + 1)
    elif key in (curses.KEY_UP, ord("k")):
        _scroll_up(state)
    elif key in (curses.KEY_DOWN, ord("j")):
        _scroll_down(state)
    elif key in (9,):
        state.focus = "explanation" if state.focus == "code" else "code"
    elif key == ord("d"):
        state.data_structures_expanded = not state.data_structures_expanded
    elif key == ord("p"):
        state.show_breadcrumb = not state.show_breadcrumb
    elif key == ord("1"):
        state.view_mode = "split"
    elif key == ord("2"):
        state.view_mode = "code"
    elif key == ord("3"):
        state.view_mode = "explanation"
    elif key in (ord("4"), ord("o")):
        state.view_mode = "overview"
    elif key == ord("+"):
        state.split_ratio = min(0.8, state.split_ratio + 0.05)
    elif key == ord("-"):
        state.split_ratio = max(0.2, state.split_ratio - 0.05)
    elif key == ord("/"):
        state.search_active = True
        state.search_query = ""
        state.search_results = []
        state.search_selected = 0
    elif key in (ord("?"),):
        _show_help(state)
    elif key == ord("r"):
        state.set_step(0)
    elif key in (curses.KEY_BACKSPACE, 127, 8):
        _go_back(state)
    elif key in (10, 13):
        _dive_into_symbol(state)
    return True


def _handle_search_key(state: UIState, key: int) -> None:
    if key in (27,):
        state.search_active = False
        state.search_query = ""
        state.search_results = []
        return
    if key in (10, 13):
        if state.search_results:
            _activate_search_result(state)
        else:
            state.search_active = False
        return
    if key in (curses.KEY_BACKSPACE, 127, 8):
        state.search_query = state.search_query[:-1]
    elif key in (curses.KEY_UP, ord("k")):
        state.search_selected = max(0, state.search_selected - 1)
        return
    elif key in (curses.KEY_DOWN, ord("j")):
        state.search_selected = min(
            len(state.search_results) - 1, state.search_selected + 1
        )
        return
    elif 32 <= key <= 126:
        state.search_query += chr(key)
    state.search_results = _perform_search(state)
    state.search_selected = 0


def _handle_overlay_key(state: UIState, key: int) -> None:
    if key in (27, ord("q")):
        state.overlay_title = None
        state.overlay_lines = []
        state.overlay_scroll = 0
        return
    if key in (curses.KEY_UP, ord("k")):
        state.overlay_scroll = max(0, state.overlay_scroll - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        state.overlay_scroll = min(
            max(0, len(state.overlay_lines) - 1), state.overlay_scroll + 1
        )


def _scroll_up(state: UIState) -> None:
    if state.focus == "code":
        if state.code_cursor > 0:
            state.code_cursor -= 1
    else:
        state.explain_scroll = max(0, state.explain_scroll - 1)


def _scroll_down(state: UIState) -> None:
    if state.focus == "code":
        code_lines = state.current_step().code.splitlines()
        if state.code_cursor < max(0, len(code_lines) - 1):
            state.code_cursor += 1
    else:
        state.explain_scroll += 1


def _dive_into_symbol(state: UIState) -> None:
    symbol = _symbol_at_cursor(state)
    if not symbol:
        state.status_message = "No symbol on current line"
        return
    target = _find_step_by_symbol(state, symbol)
    if target is not None:
        state.session.dive_stack.append(
            (
                state.session.current_step,
                state.code_cursor,
                state.code_scroll,
                state.explain_scroll,
            )
        )
        state.set_step(target)
        return
    _show_definition_for_symbol(state, symbol)


def _go_back(state: UIState) -> None:
    if not state.session.dive_stack:
        state.status_message = "Already at root"
        return
    step_idx, cursor, code_scroll, explain_scroll = state.session.dive_stack.pop()
    state.session.current_step = step_idx
    state.code_cursor = cursor
    state.code_scroll = code_scroll
    state.explain_scroll = explain_scroll


def _activate_search_result(state: UIState) -> None:
    result = state.search_results[state.search_selected]
    state.search_active = False
    if result.kind == "step" and result.step_index is not None:
        state.set_step(result.step_index)
        return
    if result.kind in ("definition", "usage") and result.file_path:
        _show_snippet(state, result.file_path, result.line_number, result.preview)
        return
    state.status_message = "No action for result"


def _show_definition_for_symbol(state: UIState, symbol: str) -> None:
    result = state.agent.tools.find_definition(symbol)
    if result.success:
        _set_overlay(state, f"Definition: {symbol}", result.output.splitlines())
    else:
        _set_overlay(state, f"Definition: {symbol}", [result.error or "Error"])


def _show_snippet(
    state: UIState, file_path: str, line_number: Optional[int], preview: Optional[str]
) -> None:
    if line_number:
        start = max(1, line_number - 4)
        end = line_number + 4
        result = state.agent.tools.read_file(file_path, start, end)
        if result.success:
            _set_overlay(state, "Snippet", result.output.splitlines())
            return
    if preview:
        _set_overlay(state, "Snippet", [preview])
        return
    _set_overlay(state, "Snippet", ["No preview available"])


def _show_help(state: UIState) -> None:
    lines = [
        "Navigation:",
        "  Left/Right or h/l  - Prev/Next step",
        "  Up/Down or k/j     - Scroll focused panel",
        "  Tab                - Toggle focus",
        "  1/2/3/4 or o        - View modes",
        "  d                  - Toggle data structures",
        "  p                  - Toggle breadcrumb",
        "",
        "Explore:",
        "  /                  - Search symbols",
        "  Enter              - Dive into symbol",
        "  Backspace          - Go back",
        "",
        "General:",
        "  r                  - Restart",
        "  q                  - Quit",
        "  Esc                - Close overlays",
    ]
    _set_overlay(state, "Help", lines)


def _set_overlay(state: UIState, title: str, lines: List[str]) -> None:
    state.overlay_title = title
    state.overlay_lines = lines or ["(empty)"]
    state.overlay_scroll = 0


def _perform_search(state: UIState) -> List[SearchResult]:
    query = state.search_query.strip()
    results: List[SearchResult] = []
    if not query:
        return results
    query_lower = query.lower()
    for idx, step in enumerate(state.session.steps):
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
        result = state.agent.tools.find_definition(query)
        if result.success:
            results.extend(_parse_definition_results(query, result.output))
    return results


def _parse_definition_results(symbol: str, output: str) -> List[SearchResult]:
    results: List[SearchResult] = []
    for line in output.splitlines():
        if not line or line.startswith("---"):
            continue
        match = re.match(r"^(.*?):(\d+):\s*(.*)$", line)
        if not match:
            continue
        file_path = match.group(1)
        try:
            line_number = int(match.group(2))
        except ValueError:
            continue
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


def _format_explanation(step: UIStep, width: int) -> List[Tuple[str, int]]:
    sections = [f"# {step.title}", ""]
    if step.flow:
        sections.extend(["**Flow:**", "```", step.flow, "```", ""])
    sections.extend(
        [
            step.explanation or "(no explanation available)",
            "",
            f"**Key Concepts:** {', '.join(step.key_concepts) if step.key_concepts else 'None'}",
            f"**Calls:** {', '.join(step.calls) if step.calls else 'None'}",
        ]
    )
    raw = "\n".join(sections)
    lines: List[Tuple[str, int]] = []
    in_code_block = False
    code_attr = curses.A_DIM
    heading_attr = curses.color_pair(COLOR_TITLE) | curses.A_BOLD
    normal_attr = curses.A_NORMAL

    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            lines.append((line, code_attr))
            continue
        if not stripped:
            lines.append(("", normal_attr))
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line.lstrip())
        if heading_match:
            text = _strip_inline_markdown(heading_match.group(2))
            wrapped = textwrap.wrap(text, width=width)
            for item in wrapped if wrapped else [text]:
                lines.append((item, heading_attr))
            continue
        list_match = re.match(r"^(\s*(?:[-*+]|\d+\.)\s+)(.*)$", line)
        if list_match:
            prefix = list_match.group(1)
            body = _strip_inline_markdown(list_match.group(2))
            wrap_width = max(10, width - len(prefix))
            wrapped = textwrap.wrap(body, width=wrap_width)
            if not wrapped:
                lines.append((prefix.rstrip(), normal_attr))
            else:
                lines.append((prefix + wrapped[0], normal_attr))
                for cont in wrapped[1:]:
                    lines.append((" " * len(prefix) + cont, normal_attr))
            continue
        text = _strip_inline_markdown(line)
        wrapped = textwrap.wrap(text, width=width)
        for item in wrapped if wrapped else [text]:
            lines.append((item, normal_attr))
    return lines


def _get_code_render(
    state: UIState, step: UIStep
) -> Tuple[List[str], List[List[Tuple[str, int]]]]:
    cache_key = state.session.current_step
    cached = state.code_cache.get(cache_key)
    if cached:
        return cached

    code_text = step.code.replace("\t", "    ")
    code_lines = code_text.splitlines() or ["(no code)"]
    line_segments = _lex_code_lines(code_text, step.file_path)

    if len(line_segments) < len(code_lines):
        line_segments.extend([[] for _ in range(len(code_lines) - len(line_segments))])

    state.code_cache[cache_key] = (code_lines, line_segments)
    return code_lines, line_segments


def _lex_code_lines(code: str, file_path: str) -> List[List[Tuple[str, int]]]:
    lexer = _get_lexer(file_path)
    tokens = lex(code, lexer)
    lines: List[List[Tuple[str, int]]] = [[]]
    for ttype, value in tokens:
        attr = _token_attr(ttype)
        parts = value.split("\n")
        for idx, part in enumerate(parts):
            if part:
                lines[-1].append((part, attr))
            if idx < len(parts) - 1:
                lines.append([])
    return lines


def _get_lexer(file_path: str):
    try:
        return get_lexer_for_filename(file_path)
    except ClassNotFound:
        return TextLexer()


def _token_attr(ttype) -> int:
    if ttype in Token.Keyword:
        return curses.color_pair(COLOR_SYNTAX_KEYWORD) | curses.A_BOLD
    if ttype in Token.String:
        return curses.color_pair(COLOR_SYNTAX_STRING)
    if ttype in Token.Comment:
        return curses.color_pair(COLOR_SYNTAX_COMMENT) | curses.A_DIM
    if ttype in Token.Number:
        return curses.color_pair(COLOR_SYNTAX_NUMBER)
    return curses.A_NORMAL


def _render_segments(
    win, y: int, x: int, segments: List[Tuple[str, int]], max_width: int, extra_attr: int
) -> None:
    remaining = max_width
    cursor_x = x
    for text, attr in segments:
        if remaining <= 0:
            break
        if not text:
            continue
        chunk = text if len(text) <= remaining else text[:remaining]
        _safe_addstr(win, y, cursor_x, chunk, attr | extra_attr)
        cursor_x += len(chunk)
        remaining -= len(chunk)


def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def _symbol_at_cursor(state: UIState) -> Optional[str]:
    step = state.current_step()
    code_lines = step.code.splitlines()
    if not code_lines or state.code_cursor >= len(code_lines):
        return None
    line = code_lines[state.code_cursor]
    match = re.search(r"([A-Za-z_][A-Za-z0-9_:]*)\s*\(", line)
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_:]*)\b", line)
    if match:
        return match.group(1)
    return None


def _find_step_by_symbol(state: UIState, symbol: str) -> Optional[int]:
    symbol_lower = symbol.lower()
    for idx, step in enumerate(state.session.steps):
        if symbol_lower in step.title.lower():
            return idx
    return None


def _clamp_code_scroll(state: UIState, total_lines: int, visible_height: int) -> None:
    if total_lines <= visible_height:
        state.code_scroll = 0
        state.code_cursor = min(state.code_cursor, max(0, total_lines - 1))
        return
    if state.code_cursor < state.code_scroll:
        state.code_scroll = state.code_cursor
    if state.code_cursor >= state.code_scroll + visible_height:
        state.code_scroll = state.code_cursor - visible_height + 1
    state.code_scroll = max(0, min(state.code_scroll, total_lines - visible_height))


def _clamp_explain_scroll(state: UIState, total_lines: int, visible_height: int) -> None:
    if total_lines <= visible_height:
        state.explain_scroll = 0
        return
    state.explain_scroll = max(
        0, min(state.explain_scroll, total_lines - visible_height)
    )


def _clamp_overlay_scroll(state: UIState, total_lines: int, visible_height: int) -> None:
    if total_lines <= visible_height:
        state.overlay_scroll = 0
        return
    state.overlay_scroll = max(
        0, min(state.overlay_scroll, total_lines - visible_height)
    )


def _draw_box(
    win, y: int, x: int, height: int, width: int, title: str = "", focused: bool = False
) -> None:
    if height < 2 or width < 2:
        return
    attr = curses.color_pair(COLOR_BORDER)
    if focused:
        attr |= curses.A_BOLD
    _safe_addch(win, y, x, curses.ACS_ULCORNER, attr)
    _safe_addch(win, y, x + width - 1, curses.ACS_URCORNER, attr)
    _safe_addch(win, y + height - 1, x, curses.ACS_LLCORNER, attr)
    _safe_addch(
        win, y + height - 1, x + width - 1, curses.ACS_LRCORNER, attr
    )
    for col in range(x + 1, x + width - 1):
        _safe_addch(win, y, col, curses.ACS_HLINE, attr)
        _safe_addch(win, y + height - 1, col, curses.ACS_HLINE, attr)
    for row in range(y + 1, y + height - 1):
        _safe_addch(win, row, x, curses.ACS_VLINE, attr)
        _safe_addch(win, row, x + width - 1, curses.ACS_VLINE, attr)
    if title:
        title_text = f" {title} "
        _safe_addstr(
            win,
            y,
            x + 2,
            _truncate(title_text, max(0, width - 4)),
            curses.color_pair(COLOR_TITLE) | curses.A_BOLD,
        )


def _fill_line(win, y: int, width: int, attr: int) -> None:
    _safe_addstr(win, y, 0, " " * (width - 1), attr)


def _safe_addstr(win, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    if x + len(text) > max_x:
        text = text[: max(0, max_x - x)]
    if not text:
        return
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def _safe_addch(win, y: int, x: int, ch: int, attr: int = 0) -> None:
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    try:
        win.addch(y, x, ch, attr)
    except curses.error:
        pass


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _key_name(key: int) -> str:
    if key == curses.KEY_LEFT:
        return "LEFT"
    if key == curses.KEY_RIGHT:
        return "RIGHT"
    if key == curses.KEY_UP:
        return "UP"
    if key == curses.KEY_DOWN:
        return "DOWN"
    if key == 9:
        return "TAB"
    if key == 27:
        return "ESC"
    if 32 <= key <= 126:
        return chr(key)
    return str(key)


def _ensure_tty_input() -> bool:
    if sys.stdin.isatty():
        return True
    try:
        tty_path = os.ctermid()
    except Exception:
        tty_path = "/dev/tty"
    try:
        tty_fd = os.open(tty_path, os.O_RDWR)
        os.dup2(tty_fd, 0)
        os.close(tty_fd)
        return True
    except Exception:
        return False
