## Terminal UI Design

### 1. Overall Layout

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 🚶 Code Walker                                    Step 3/7 │ leveldb/db/db_impl.cc │
├────────────────────────────────────────────┬────────────────────────────────────────┤
│                                            │                                        │
│  CODE                                      │  EXPLANATION                           │
│                                            │                                        │
│  140│                                      │  ## DBImpl::Write()                    │
│  141│ Status DBImpl::Write(                │                                        │
│  142│     const WriteOptions& options,     │  This is the core write path where     │
│  143│     WriteBatch* updates) {           │  LevelDB batches multiple writes       │
│  144│                                      │  together for efficiency.              │
│  145│   Writer w(&mutex_);                 │                                        │
│  146│   w.batch = updates;                 │  **Key Operations:**                   │
│  147│   w.sync = options.sync;             │                                        │
│  148│   w.done = false;                    │  1. Creates a Writer struct to hold    │
│> 149│                                      │     this write's state (line 145)      │
│  150│   MutexLock l(&mutex_);              │                                        │
│  151│   writers_.push_back(&w);            │  2. Acquires mutex and joins the       │
│  152│                                      │     writer queue (lines 150-151)       │
│  153│   // Wait until we're at front       │                                        │
│  154│   while (!w.done &&                  │  3. Waits until this writer becomes    │
│  155│          &w != writers_.front()) {   │     the leader (lines 154-157)         │
│  156│     w.cv.Wait();                     │                                        │
│  157│   }                                  │  4. Leader batches writes and syncs    │
│  158│                                      │     to WAL (not shown, scroll down)    │
│  159│   if (w.done) {                      │                                        │
│  160│     return w.status;                 │  ─────────────────────────────────     │
│  161│   }                                  │                                        │
│  162│                                      │  **Why This Matters:**                 │
│  163│   // Make room in memtable           │  The leader election pattern reduces   │
│  164│   Status status = MakeRoomForWrite(  │  lock contention and allows batching   │
│  165│       updates == nullptr);           │  multiple writes into a single WAL     │
│  166│                                      │  sync, dramatically improving          │
│  167│   uint64_t last_sequence =           │  throughput under concurrent load.     │
│  168│       versions_->LastSequence();     │                                        │
│  169│   ...                                │                                        │
│                                            │                                        │
├────────────────────────────────────────────┴────────────────────────────────────────┤
│  📦 Data Structures    [D]                 │  🔍 Find Symbol    [/]                 │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │ Writer { WriteBatch* batch; bool sync; bool done; CondVar cv; Status status }│  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  Path: Put() → Write() → [MakeRoomForWrite()] → WriteToWAL() → InsertMemtable()    │
│                            ▲ you are here                                           │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  [←] Prev  [→] Next  [Enter] Dive into MakeRoomForWrite  [Tab] TogglePane  [q] Quit│
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Component Breakdown

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                 HEADER BAR                                          │
│  • App name + icon                                                                  │
│  • Current step / total steps                                                       │
│  • Current file path                                                                │
├────────────────────────────────────────────┬────────────────────────────────────────┤
│                                            │                                        │
│              CODE PANEL                    │           EXPLANATION PANEL            │
│                                            │                                        │
│  • Syntax highlighted code                 │  • Step title                          │
│  • Line numbers                            │  • Natural language explanation        │
│  • Current line indicator (>)              │  • Key operations list                 │
│  • Scroll indicator                        │  • Why it matters section              │
│  • Highlighted regions                     │  • Scrollable                          │
│                                            │                                        │
├────────────────────────────────────────────┴────────────────────────────────────────┤
│                              DATA STRUCTURES BAR                                    │
│  • Collapsible panel showing relevant types                                         │
│  • Quick reference for current step                                                 │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                 PATH BREADCRUMB                                     │
│  • Visual representation of the full code path                                      │
│  • Current position indicator                                                       │
│  • Clickable/navigable steps                                                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                  ACTION BAR                                         │
│  • Navigation shortcuts                                                             │
│  • Available actions for current context                                            │
│  • Help hints                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 3. View Modes

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              VIEW MODES                                             │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  MODE 1: Split View (Default)                                                       │
│  ┌─────────────────────────┬─────────────────────────┐                             │
│  │         CODE            │      EXPLANATION        │                             │
│  │                         │                         │                             │
│  └─────────────────────────┴─────────────────────────┘                             │
│  Toggle: [Tab] to switch focus, [1] for this mode                                  │
│                                                                                     │
│  ─────────────────────────────────────────────────────────────────────────────     │
│                                                                                     │
│  MODE 2: Code Focus (Full Width Code)                                              │
│  ┌───────────────────────────────────────────────────┐                             │
│  │                                                   │                             │
│  │                      CODE                         │                             │
│  │                   (full width)                    │                             │
│  │                                                   │                             │
│  └───────────────────────────────────────────────────┘                             │
│  Toggle: [2] for this mode, [e] to show explanation overlay                        │
│                                                                                     │
│  ─────────────────────────────────────────────────────────────────────────────     │
│                                                                                     │
│  MODE 3: Explanation Focus                                                          │
│  ┌───────────────────────────────────────────────────┐                             │
│  │                                                   │                             │
│  │                  EXPLANATION                      │                             │
│  │                  (full width)                     │                             │
│  │              + inline code snippets               │                             │
│  │                                                   │                             │
│  └───────────────────────────────────────────────────┘                             │
│  Toggle: [3] for this mode                                                         │
│                                                                                     │
│  ─────────────────────────────────────────────────────────────────────────────     │
│                                                                                     │
│  MODE 4: Overview (Path Map)                                                        │
│  ┌───────────────────────────────────────────────────┐                             │
│  │  ┌─────┐    ┌─────┐    ┌─────┐    ┌─────┐        │                             │
│  │  │Put()│───▶│Write│───▶│ WAL │───▶│ Mem │        │                             │
│  │  └─────┘    └──┬──┘    └─────┘    └─────┘        │                             │
│  │               │                                   │                             │
│  │               ▼                                   │                             │
│  │          ┌─────────┐                              │                             │
│  │          │MakeRoom │                              │                             │
│  │          └─────────┘                              │                             │
│  └───────────────────────────────────────────────────┘                             │
│  Toggle: [4] or [o] for overview                                                   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 4. Interactive Elements

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           INTERACTIVE ELEMENTS                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  SYMBOL HOVER / INSPECTION                                                          │
│  ─────────────────────────────────────────────────────────────────────────────      │
│  When cursor is on a symbol, show inline popup:                                     │
│                                                                                     │
│     167│   uint64_t last_sequence =                                                │
│     168│       versions_->LastSequence();                                          │
│                         ▲                                                           │
│           ┌─────────────┴──────────────────────────────┐                           │
│           │ LastSequence() -> uint64_t                 │                           │
│           │ Returns the last assigned sequence number  │                           │
│           │ File: db/version_set.cc:234                │                           │
│           │ [Enter] Go to definition  [Esc] Close      │                           │
│           └────────────────────────────────────────────┘                           │
│                                                                                     │
│  ─────────────────────────────────────────────────────────────────────────────      │
│                                                                                     │
│  SEARCH / FIND SYMBOL                                                               │
│  ─────────────────────────────────────────────────────────────────────────────      │
│  Press [/] to open search:                                                          │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │ 🔍 Find: WriteBatch█                                                        │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │  → class WriteBatch          include/leveldb/write_batch.h:24              │   │
│  │    WriteBatch::Put           db/write_batch.cc:45                           │   │
│  │    WriteBatch::Delete        db/write_batch.cc:67                           │   │
│  │    WriteBatch::Iterate       db/write_batch.cc:89                           │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ─────────────────────────────────────────────────────────────────────────────      │
│                                                                                     │
│  DIVE INTO / CALL STACK                                                             │
│  ─────────────────────────────────────────────────────────────────────────────      │
│  Press [Enter] on a function call to dive in, [Backspace] to go back:              │
│                                                                                     │
│  ┌─ Call Stack ─────────────────────────────────────────┐                          │
│  │  1. DBImpl::Put()           db/db_impl.cc:123       │                          │
│  │  2. DBImpl::Write()         db/db_impl.cc:141       │                          │
│  │  3. DBImpl::MakeRoomForWrite() ← current            │                          │
│  └──────────────────────────────────────────────────────┘                          │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 5. Keyboard Shortcuts

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              KEYBOARD SHORTCUTS                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  NAVIGATION                          │  VIEW CONTROLS                              │
│  ────────────────────────────────    │  ────────────────────────────────           │
│  ←/h    Previous step                │  Tab      Toggle focus (code/explanation)  │
│  →/l    Next step                    │  1        Split view mode                   │
│  ↑/k    Scroll up in current panel   │  2        Code focus mode                   │
│  ↓/j    Scroll down                  │  3        Explanation focus mode            │
│  g      Go to first step             │  4/o      Overview/path map mode            │
│  G      Go to last step              │  d        Toggle data structures panel      │
│  [n]    Jump to step n               │  p        Toggle path breadcrumb            │
│                                      │  +/-      Adjust split ratio                │
│                                      │                                              │
│  CODE EXPLORATION                    │  SEARCH & INFO                              │
│  ────────────────────────────────    │  ────────────────────────────────           │
│  Enter  Dive into symbol at cursor   │  /        Search symbols                    │
│  Backspace  Go back in dive stack    │  ?        Show help                         │
│  f      Find usages of symbol        │  i        Show file info                    │
│  t      Show type definition         │  c        Show git blame for line           │
│                                      │                                              │
│  GENERAL                             │                                              │
│  ────────────────────────────────    │                                              │
│  q      Quit                         │                                              │
│  r      Restart walk-through         │                                              │
│  s      Save session                 │                                              │
│  Ctrl+e Export as markdown           │                                              │
│                                      │                                              │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 6. Implementation with Textual

```python
"""
Code Walker TUI - Built with Textual

Dependencies:
    pip install textual rich pygments
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Label, 
    ListView, ListItem, Input, Button
)
from textual.binding import Binding
from textual.reactive import reactive
from textual import events
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from dataclasses import dataclass
from typing import List, Optional
import asyncio


# ============== Data Models ==============

@dataclass
class WalkStep:
    step_number: int
    title: str
    file_path: str
    code: str
    start_line: int
    explanation: str
    data_structures: List[dict]
    key_concepts: List[str]
    calls: List[str]  # Functions this step calls (for diving)

@dataclass 
class WalkSession:
    title: str
    overview: str
    steps: List[WalkStep]
    current_step: int = 0
    dive_stack: List[tuple] = None  # (step_idx, scroll_pos) for back navigation
    
    def __post_init__(self):
        if self.dive_stack is None:
            self.dive_stack = []


# ============== Custom Widgets ==============

class CodePanel(Static):
    """Syntax-highlighted code panel with line numbers."""
    
    code = reactive("")
    language = reactive("python")
    start_line = reactive(1)
    highlight_lines = reactive(set())
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.scroll_offset = 0
    
    def render(self) -> Syntax:
        return Syntax(
            self.code,
            self.language,
            theme="monokai",
            line_numbers=True,
            start_line=self.start_line,
            highlight_lines=self.highlight_lines,
            word_wrap=False,
        )
    
    def scroll_to_line(self, line: int):
        """Scroll to make a specific line visible."""
        # Implementation depends on container
        pass


class ExplanationPanel(Static):
    """Markdown-rendered explanation panel."""
    
    content = reactive("")
    
    def render(self) -> Markdown:
        return Markdown(self.content)


class DataStructuresBar(Static):
    """Collapsible bar showing relevant data structures."""
    
    structures = reactive([])
    expanded = reactive(False)
    
    def render(self):
        if not self.structures:
            return Text("No data structures for this step", style="dim")
        
        if not self.expanded:
            # Collapsed view - one line summary
            names = [s.get('name', '?') for s in self.structures]
            return Text(f"📦 Data Structures: {', '.join(names)}  [d to expand]", 
                       style="bold cyan")
        
        # Expanded view
        lines = ["📦 Data Structures:\n"]
        for struct in self.structures:
            lines.append(f"\n{struct.get('name', 'Unknown')}:")
            lines.append(f"```\n{struct.get('definition', '')}\n```")
        
        return Markdown("\n".join(lines))
    
    def toggle(self):
        self.expanded = not self.expanded


class PathBreadcrumb(Static):
    """Visual breadcrumb showing the code path."""
    
    steps = reactive([])
    current = reactive(0)
    
    def render(self):
        if not self.steps:
            return Text("")
        
        parts = []
        for i, step in enumerate(self.steps):
            name = step.title.split(":")[-1].strip()[:20]
            if i == self.current:
                parts.append(f"[bold reverse cyan] {name} [/]")
            else:
                parts.append(f"[dim]{name}[/]")
        
        path_str = " → ".join(parts)
        return Text.from_markup(f"Path: {path_str}")


class SymbolPopup(Static):
    """Popup showing symbol information."""
    
    def __init__(self, symbol: str, info: dict, **kwargs):
        super().__init__(**kwargs)
        self.symbol = symbol
        self.info = info
    
    def render(self):
        return Panel(
            f"""[bold]{self.symbol}[/bold]
            
{self.info.get('signature', '')}

{self.info.get('description', '')}

[dim]File: {self.info.get('file', 'unknown')}[/dim]

[dim][Enter] Go to definition  [Esc] Close[/dim]""",
            title="Symbol Info",
            border_style="cyan"
        )


class SearchModal(Static):
    """Search modal for finding symbols."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.query = ""
        self.results = []
        self.selected = 0
    
    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search symbols...", id="search-input")
        yield ListView(id="search-results")
    
    def on_input_changed(self, event: Input.Changed):
        self.query = event.value
        # Trigger search (would call agent tools)
        self.results = self._search(self.query)
        self._update_results()
    
    def _search(self, query: str) -> List[dict]:
        # This would call the actual search tools
        return []
    
    def _update_results(self):
        results_view = self.query_one("#search-results", ListView)
        results_view.clear()
        for result in self.results[:10]:
            results_view.append(
                ListItem(Label(f"{result['name']}  {result['file']}"))
            )


# ============== Main Application ==============

class CodeWalkerApp(App):
    """Main Code Walker TUI Application."""
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto auto auto;
    }
    
    #main-container {
        layout: horizontal;
    }
    
    #code-panel {
        width: 1fr;
        border: solid green;
        overflow-y: auto;
    }
    
    #explanation-panel {
        width: 1fr;
        border: solid blue;
        overflow-y: auto;
        padding: 1;
    }
    
    #data-structures-bar {
        height: auto;
        max-height: 8;
        border: solid cyan;
        padding: 0 1;
    }
    
    #path-breadcrumb {
        height: 3;
        border: solid yellow;
        padding: 0 1;
    }
    
    .focused {
        border: double green;
    }
    
    #search-modal {
        layer: modal;
        width: 60%;
        height: 50%;
        margin: 4 8;
        border: solid cyan;
        background: $surface;
    }
    
    #search-modal Input {
        margin: 1;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("left,h", "prev_step", "Previous"),
        Binding("right,l", "next_step", "Next"),
        Binding("tab", "toggle_focus", "Toggle Focus"),
        Binding("d", "toggle_data", "Data Structures"),
        Binding("/", "search", "Search"),
        Binding("enter", "dive_in", "Dive In"),
        Binding("backspace", "go_back", "Go Back"),
        Binding("1", "split_view", "Split View"),
        Binding("2", "code_view", "Code View"),
        Binding("3", "explain_view", "Explain View"),
        Binding("4,o", "overview", "Overview"),
        Binding("?", "help", "Help"),
    ]
    
    # Reactive state
    current_step = reactive(0)
    focus_panel = reactive("code")  # "code" or "explanation"
    view_mode = reactive("split")   # "split", "code", "explanation", "overview"
    
    def __init__(self, session: WalkSession):
        super().__init__()
        self.session = session
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Horizontal(id="main-container"):
            yield CodePanel(id="code-panel")
            yield ExplanationPanel(id="explanation-panel")
        
        yield DataStructuresBar(id="data-structures-bar")
        yield PathBreadcrumb(id="path-breadcrumb")
        
        yield Footer()
    
    def on_mount(self):
        """Initialize the UI with first step."""
        self._update_display()
        self._update_title()
    
    def _update_display(self):
        """Update all panels with current step data."""
        if not self.session.steps:
            return
        
        step = self.session.steps[self.current_step]
        
        # Update code panel
        code_panel = self.query_one("#code-panel", CodePanel)
        code_panel.code = step.code
        code_panel.start_line = step.start_line
        code_panel.language = self._detect_language(step.file_path)
        
        # Update explanation panel
        explain_panel = self.query_one("#explanation-panel", ExplanationPanel)
        explain_panel.content = self._format_explanation(step)
        
        # Update data structures bar
        ds_bar = self.query_one("#data-structures-bar", DataStructuresBar)
        ds_bar.structures = step.data_structures
        
        # Update path breadcrumb
        breadcrumb = self.query_one("#path-breadcrumb", PathBreadcrumb)
        breadcrumb.steps = self.session.steps
        breadcrumb.current = self.current_step
    
    def _format_explanation(self, step: WalkStep) -> str:
        """Format step explanation as markdown."""
        return f"""## {step.title}

{step.explanation}

---

**Key Concepts:** {', '.join(step.key_concepts) if step.key_concepts else 'None'}

**Calls:** {', '.join(step.calls) if step.calls else 'None'}
"""
    
    def _update_title(self):
        """Update the header title."""
        step = self.session.steps[self.current_step] if self.session.steps else None
        if step:
            self.title = f"Code Walker - Step {self.current_step + 1}/{len(self.session.steps)} │ {step.file_path}"
        else:
            self.title = "Code Walker"
    
    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
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
    
    # ========== Actions ==========
    
    def action_prev_step(self):
        """Go to previous step."""
        if self.current_step > 0:
            self.current_step -= 1
            self._update_display()
            self._update_title()
    
    def action_next_step(self):
        """Go to next step."""
        if self.current_step < len(self.session.steps) - 1:
            self.current_step += 1
            self._update_display()
            self._update_title()
    
    def action_toggle_focus(self):
        """Toggle focus between code and explanation panels."""
        code_panel = self.query_one("#code-panel")
        explain_panel = self.query_one("#explanation-panel")
        
        if self.focus_panel == "code":
            self.focus_panel = "explanation"
            code_panel.remove_class("focused")
            explain_panel.add_class("focused")
        else:
            self.focus_panel = "code"
            explain_panel.remove_class("focused")
            code_panel.add_class("focused")
    
    def action_toggle_data(self):
        """Toggle data structures panel."""
        ds_bar = self.query_one("#data-structures-bar", DataStructuresBar)
        ds_bar.toggle()
    
    def action_search(self):
        """Open search modal."""
        # Would mount SearchModal
        self.notify("Search: Not yet implemented")
    
    def action_dive_in(self):
        """Dive into a function call."""
        step = self.session.steps[self.current_step]
        if step.calls:
            # Save current position to stack
            self.session.dive_stack.append((self.current_step, 0))
            # Find step for first callable (simplified)
            self.notify(f"Dive into: {step.calls[0]} (not implemented)")
    
    def action_go_back(self):
        """Go back in dive stack."""
        if self.session.dive_stack:
            prev_step, _ = self.session.dive_stack.pop()
            self.current_step = prev_step
            self._update_display()
            self._update_title()
        else:
            self.notify("Already at root")
    
    def action_split_view(self):
        """Switch to split view mode."""
        self.view_mode = "split"
        self._apply_view_mode()
    
    def action_code_view(self):
        """Switch to code-only view mode."""
        self.view_mode = "code"
        self._apply_view_mode()
    
    def action_explain_view(self):
        """Switch to explanation-only view mode."""
        self.view_mode = "explanation"
        self._apply_view_mode()
    
    def action_overview(self):
        """Switch to overview mode."""
        self.view_mode = "overview"
        self.notify("Overview mode: Not yet implemented")
    
    def _apply_view_mode(self):
        """Apply the current view mode to panels."""
        code_panel = self.query_one("#code-panel")
        explain_panel = self.query_one("#explanation-panel")
        
        if self.view_mode == "split":
            code_panel.styles.display = "block"
            explain_panel.styles.display = "block"
            code_panel.styles.width = "1fr"
            explain_panel.styles.width = "1fr"
        elif self.view_mode == "code":
            code_panel.styles.display = "block"
            explain_panel.styles.display = "none"
            code_panel.styles.width = "100%"
        elif self.view_mode == "explanation":
            code_panel.styles.display = "none"
            explain_panel.styles.display = "block"
            explain_panel.styles.width = "100%"
    
    def action_help(self):
        """Show help."""
        help_text = """
Code Walker Shortcuts:
  ←/→ or h/l : Navigate steps
  Tab        : Toggle focus
  Enter      : Dive into function
  Backspace  : Go back
  d          : Toggle data structures
  /          : Search symbols
  1-4        : Change view mode
  q          : Quit
        """
        self.notify(help_text, timeout=10)


# ============== Entry Point ==============

def run_tui(session: WalkSession):
    """Run the TUI with a walk session."""
    app = CodeWalkerApp(session)
    app.run()


# Example usage
if __name__ == "__main__":
    # Demo session for testing
    demo_session = WalkSession(
        title="LevelDB Write Path",
        overview="Understanding how Put() writes data to disk",
        steps=[
            WalkStep(
                step_number=1,
                title="Entry Point: DBImpl::Put()",
                file_path="db/db_impl.cc",
                code='''Status DBImpl::Put(const WriteOptions& options,
                   const Slice& key,
                   const Slice& value) {
  WriteBatch batch;
  batch.Put(key, value);
  return Write(options, &batch);
}''',
                start_line=123,
                explanation="""This is the public entry point for writing a key-value pair.

The implementation wraps the single Put into a WriteBatch and delegates to Write().
This allows all writes (single and batch) to share the same optimized code path.""",
                data_structures=[{
                    "name": "WriteBatch",
                    "definition": "class WriteBatch { void Put(Slice, Slice); string rep_; }"
                }],
                key_concepts=["Write batching", "Uniform interface"],
                calls=["WriteBatch::Put", "DBImpl::Write"]
            ),
            WalkStep(
                step_number=2,
                title="Write Batching: DBImpl::Write()",
                file_path="db/db_impl.cc",
                code='''Status DBImpl::Write(const WriteOptions& options, 
                     WriteBatch* updates) {
  Writer w(&mutex_);
  w.batch = updates;
  w.sync = options.sync;
  w.done = false;
  
  MutexLock l(&mutex_);
  writers_.push_back(&w);
  
  while (!w.done && &w != writers_.front()) {
    w.cv.Wait();
  }
  
  if (w.done) {
    return w.status;
  }
  
  // Leader does the actual write...
}''',
                start_line=141,
                explanation="""This is where the write batching magic happens.

Multiple concurrent writers queue up and the "leader" (front of queue) 
batches them together for a single WAL write. This dramatically improves
throughput under concurrent load.""",
                data_structures=[{
                    "name": "Writer",
                    "definition": "struct Writer { WriteBatch* batch; bool sync; bool done; CondVar cv; }"
                }],
                key_concepts=["Leader election", "Write batching", "Mutex"],
                calls=["MakeRoomForWrite", "WriteBatchInternal::SetSequence"]
            ),
        ]
    )
    
    run_tui(demo_session)
```

---

### 7. Alternative: Rich-only Implementation (Simpler)

If you want something lighter without the full Textual framework:

```python
"""
Code Walker TUI - Simple version using only Rich
Good for quick iteration, less complex than Textual
"""

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.table import Table
from dataclasses import dataclass
from typing import List
import sys
import tty
import termios


class SimpleCodeWalkerTUI:
    """Simple TUI using Rich's Layout and Live display."""
    
    def __init__(self, session):
        self.session = session
        self.current_step = 0
        self.console = Console()
        self.code_scroll = 0
        self.explain_scroll = 0
        self.show_data_structures = True
        self.focus = "code"  # or "explanation"
    
    def make_layout(self) -> Layout:
        """Create the layout structure."""
        layout = Layout()
        
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="data_structures", size=5),
            Layout(name="breadcrumb", size=3),
            Layout(name="footer", size=3),
        )
        
        layout["main"].split_row(
            Layout(name="code", ratio=1),
            Layout(name="explanation", ratio=1),
        )
        
        return layout
    
    def render_header(self) -> Panel:
        """Render the header bar."""
        step = self.session.steps[self.current_step]
        
        title = Text()
        title.append("🚶 Code Walker", style="bold cyan")
        title.append("  │  ", style="dim")
        title.append(f"Step {self.current_step + 1}/{len(self.session.steps)}", 
                    style="bold yellow")
        title.append("  │  ", style="dim")
        title.append(step.file_path, style="green")
        
        return Panel(title, style="bold")
    
    def render_code(self) -> Panel:
        """Render the code panel."""
        step = self.session.steps[self.current_step]
        
        syntax = Syntax(
            step.code,
            self._detect_language(step.file_path),
            theme="monokai",
            line_numbers=True,
            start_line=step.start_line,
            word_wrap=False,
        )
        
        border_style = "bold green" if self.focus == "code" else "green"
        return Panel(
            syntax, 
            title=f"[bold]{step.title}[/bold]",
            border_style=border_style,
            padding=(0, 1),
        )
    
    def render_explanation(self) -> Panel:
        """Render the explanation panel."""
        step = self.session.steps[self.current_step]
        
        md_content = f"""## {step.title}

{step.explanation}

---

**Key Concepts:** {', '.join(step.key_concepts) if step.key_concepts else 'None'}

**Calls:** {', '.join(f'`{c}`' for c in step.calls) if step.calls else 'None'}
"""
        
        border_style = "bold blue" if self.focus == "explanation" else "blue"
        return Panel(
            Markdown(md_content),
            title="[bold]Explanation[/bold]",
            border_style=border_style,
            padding=(0, 1),
        )
    
    def render_data_structures(self) -> Panel:
        """Render the data structures bar."""
        step = self.session.steps[self.current_step]
        
        if not step.data_structures:
            return Panel(
                Text("No data structures for this step", style="dim"),
                title="📦 Data Structures",
                border_style="cyan",
                height=5,
            )
        
        if not self.show_data_structures:
            names = [s.get('name', '?') for s in step.data_structures]
            return Panel(
                Text(f"📦 {', '.join(names)}  [d to expand]", style="cyan"),
                border_style="cyan",
                height=3,
            )
        
        # Expanded view
        table = Table(show_header=False, box=None, padding=(0, 1))
        for struct in step.data_structures:
            table.add_row(
                Text(struct.get('name', ''), style="bold cyan"),
                Text(struct.get('definition', '')[:60] + "...", style="dim")
            )
        
        return Panel(
            table,
            title="📦 Data Structures [d to collapse]",
            border_style="cyan",
        )
    
    def render_breadcrumb(self) -> Panel:
        """Render the path breadcrumb."""
        parts = []
        for i, step in enumerate(self.session.steps):
            name = step.title.split(":")[-1].strip()[:15]
            if i == self.current_step:
                parts.append(f"[bold reverse cyan] {name} [/]")
            else:
                parts.append(f"[dim]{name}[/]")
        
        path_text = " → ".join(parts)
        return Panel(
            Text.from_markup(f"Path: {path_text}"),
            border_style="yellow",
        )
    
    def render_footer(self) -> Panel:
        """Render the footer with shortcuts."""
        shortcuts = Text()
        shortcuts.append(" [←/h] ", style="bold")
        shortcuts.append("Prev  ", style="dim")
        shortcuts.append("[→/l] ", style="bold")
        shortcuts.append("Next  ", style="dim")
        shortcuts.append("[Tab] ", style="bold")
        shortcuts.append("Focus  ", style="dim")
        shortcuts.append("[d] ", style="bold")
        shortcuts.append("Data  ", style="dim")
        shortcuts.append("[q] ", style="bold")
        shortcuts.append("Quit", style="dim")
        
        return Panel(shortcuts, style="dim")
    
    def render(self) -> Layout:
        """Render the complete layout."""
        layout = self.make_layout()
        
        layout["header"].update(self.render_header())
        layout["code"].update(self.render_code())
        layout["explanation"].update(self.render_explanation())
        layout["data_structures"].update(self.render_data_structures())
        layout["breadcrumb"].update(self.render_breadcrumb())
        layout["footer"].update(self.render_footer())
        
        return layout
    
    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext_map = {
            ".py": "python", ".go": "go", ".rs": "rust",
            ".js": "javascript", ".ts": "typescript",
            ".cc": "cpp", ".cpp": "cpp", ".c": "c", ".h": "cpp",
            ".java": "java", ".rb": "ruby",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return "text"
    
    def get_key(self) -> str:
        """Get a single keypress."""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            # Handle escape sequences (arrow keys)
            if ch == '\x1b':
                ch += sys.stdin.read(2)
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    
    def run(self):
        """Main run loop."""
        with Live(self.render(), console=self.console, 
                  refresh_per_second=10, screen=True) as live:
            while True:
                key = self.get_key()
                
                if key in ('q', '\x03'):  # q or Ctrl+C
                    break
                elif key in ('\x1b[D', 'h'):  # Left arrow or h
                    if self.current_step > 0:
                        self.current_step -= 1
                elif key in ('\x1b[C', 'l'):  # Right arrow or l
                    if self.current_step < len(self.session.steps) - 1:
                        self.current_step += 1
                elif key == '\t':  # Tab
                    self.focus = "explanation" if self.focus == "code" else "code"
                elif key == 'd':
                    self.show_data_structures = not self.show_data_structures
                elif key == '\x1b[A':  # Up arrow
                    pass  # Would scroll
                elif key == '\x1b[B':  # Down arrow
                    pass  # Would scroll
                
                live.update(self.render())


# Run the simple TUI
def run_simple_tui(session):
    tui = SimpleCodeWalkerTUI(session)
    tui.run()
```

---

### 8. Summary of UI Components

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **Header** | Context info | Step counter, file path |
| **Code Panel** | Show source code | Syntax highlighting, line numbers, scroll |
| **Explanation Panel** | AI-generated explanation | Markdown rendering, key concepts |
| **Data Structures Bar** | Quick type reference | Collapsible, inline definitions |
| **Path Breadcrumb** | Show code path | Navigable, current position |
| **Footer** | Keyboard shortcuts | Context-aware hints |
| **Search Modal** | Find symbols | Fuzzy search, results list |
| **Symbol Popup** | Inline info | Definition, go-to |

---