## Interactive Q&A Design

### 1. Overview

Allow users to ask questions during any walkthrough step. The agent answers based on the code being discussed, with full context of the current step.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INTERACTIVE Q&A FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐                                                          │
│   │  Walk Step   │  User viewing Step 3: DBImpl::Write()                    │
│   │   Display    │                                                          │
│   └──────┬───────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│   ┌──────────────┐      Empty input?         ┌──────────────┐              │
│   │ Wait for     │ ─────────YES─────────────▶│  Next Step   │              │
│   │ User Input   │                           └──────────────┘              │
│   └──────┬───────┘                                                          │
│          │ Question entered                                                  │
│          ▼                                                                   │
│   ┌──────────────┐                                                          │
│   │ CodeTutor    │  Context: step code + explanation + overview             │
│   │    Agent     │                                                          │
│   └──────┬───────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│   ┌──────────────┐                                                          │
│   │   Display    │  Show answer, return to input prompt                     │
│   │   Answer     │                                                          │
│   └──────┬───────┘                                                          │
│          │                                                                   │
│          └──────────────────────────────────────────────────────────────────┤
│                              (loop back to input)                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 2. CodeTutorAgent Design

A specialized agent focused on answering questions about code in a teaching-oriented style.

**Update: Line-numbered code for precise references**

To ensure the tutor can cite exact line numbers, provide the step's code with line numbers embedded before injecting it into the prompt.

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from anthropic import Anthropic


@dataclass
class TutorContext:
    """Context provided to the tutor for answering questions."""
    # Current step info
    step_title: str
    step_number: int
    file_path: str
    start_line: int
    end_line: int
    code: str
    explanation: str
    flow_diagram: Optional[str] = None

    # Walkthrough context
    walkthrough_title: str
    walkthrough_overview: str
    total_steps: int

    # Conversation history within this step
    qa_history: List[Dict] = field(default_factory=list)


@dataclass
class TutorResponse:
    """Response from the tutor agent."""
    answer: str
    references: List[str] = field(default_factory=list)  # File paths or symbols mentioned
    follow_up_suggestions: List[str] = field(default_factory=list)


class CodeTutorAgent:
    """
    Agent for answering user questions about code during a walkthrough.

    Responsibilities:
    - Answer questions about the current step's code
    - Explain concepts, patterns, and idioms
    - Navigate to related code when asked
    - Maintain conversational context within a step
    """

    SYSTEM_PROMPT = """You are a code tutor helping someone understand a codebase.

You are currently explaining step {step_number} of {total_steps} in a walkthrough titled "{walkthrough_title}".

## Current Step Context

**Title:** {step_title}
**File:** {file_path} (lines {start_line}-{end_line})

**Code (line-numbered):**
```
{code}
```

**Pre-generated Explanation:**
{explanation}

**Flow Diagram:**
{flow_diagram}

## Walkthrough Overview
{walkthrough_overview}

## Your Role

1. Answer the user's question clearly and concisely
2. Reference specific line numbers when discussing code
3. Connect concepts to the broader walkthrough context when relevant
4. Use analogies and examples to clarify complex ideas
5. If the question is about code outside this step, you can use tools to find it

## Guidelines

- Be conversational but precise
- Don't repeat information the user already knows
- If you're unsure, say so rather than guessing
- Offer follow-up questions the user might want to ask
"""

    def __init__(self, repo_path: str, model: str = "claude-sonnet-4-20250514"):
        self.repo_path = repo_path
        self.model = model
        self.client = Anthropic()
        self.tools = self._build_tools()

    def _build_tools(self) -> List[Dict]:
        """Build tool definitions for the tutor agent."""
        return [
            {
                "name": "read_file",
                "description": "Read a file from the repository. Use when the user asks about code in a different file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file relative to repo root"
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Starting line number (1-indexed)"
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Ending line number (1-indexed)"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "search_code",
                "description": "Search for a pattern in the codebase. Use when looking for where something is defined or used.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Search pattern (regex supported)"
                        },
                        "file_pattern": {
                            "type": "string",
                            "description": "Glob pattern to filter files (e.g., '*.py')"
                        }
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "find_definition",
                "description": "Find where a symbol (function, class, type) is defined.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Name of the symbol to find"
                        }
                    },
                    "required": ["symbol"]
                }
            },
            {
                "name": "find_usages",
                "description": "Find all places where a symbol is used.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Name of the symbol to find usages of"
                        }
                    },
                    "required": ["symbol"]
                }
            }
        ]

    def _format_code_with_lines(self, code: str, start_line: int) -> str:
        """Add line numbers so the tutor can reference exact lines."""
        return "\n".join(
            f"{i:>4} | {line}"
            for i, line in enumerate(code.splitlines(), start_line)
        )

    def answer_question(
        self,
        question: str,
        context: TutorContext
    ) -> TutorResponse:
        """
        Answer a user question about the current step.

        Args:
            question: The user's question
            context: Current step and walkthrough context

        Returns:
            TutorResponse with the answer and optional references
        """
        # Build system prompt with context
        code_with_lines = self._format_code_with_lines(context.code, context.start_line)
        system = self.SYSTEM_PROMPT.format(
            step_number=context.step_number,
            total_steps=context.total_steps,
            walkthrough_title=context.walkthrough_title,
            step_title=context.step_title,
            file_path=context.file_path,
            start_line=context.start_line,
            end_line=context.end_line,
            code=code_with_lines,
            explanation=context.explanation,
            flow_diagram=context.flow_diagram or "(none)",
            walkthrough_overview=context.walkthrough_overview,
        )

        # Build messages from history + new question
        messages = []
        for qa in context.qa_history:
            messages.append({"role": "user", "content": qa["question"]})
            messages.append({"role": "assistant", "content": qa["answer"]})
        messages.append({"role": "user", "content": question})

        # Call the model with tools
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system,
            tools=self.tools,
            messages=messages,
        )

        # Handle tool use if needed
        while response.stop_reason == "tool_use":
            # Execute tool calls
            tool_results = self._execute_tools(response.content)

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                tools=self.tools,
                messages=messages,
            )

        # Extract answer text
        answer = ""
        for block in response.content:
            if hasattr(block, "text"):
                answer = block.text
                break

        return TutorResponse(
            answer=answer,
            references=self._extract_references(answer),
            follow_up_suggestions=self._extract_follow_ups(answer),
        )

    def _execute_tools(self, content) -> List[Dict]:
        """Execute tool calls and return results."""
        results = []
        for block in content:
            if block.type == "tool_use":
                result = self._execute_single_tool(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        return results

    def _execute_single_tool(self, name: str, args: Dict) -> str:
        """Execute a single tool and return the result."""
        # Implementation would use CodeWalkerTools or similar
        # Simplified here for design doc
        if name == "read_file":
            return f"(File content of {args['path']})"
        elif name == "search_code":
            return f"(Search results for '{args['pattern']}')"
        elif name == "find_definition":
            return f"(Definition of {args['symbol']})"
        elif name == "find_usages":
            return f"(Usages of {args['symbol']})"
        return "(Unknown tool)"

    def _extract_references(self, answer: str) -> List[str]:
        """Extract file/symbol references from the answer."""
        # Would parse the answer for file paths and symbols
        return []

    def _extract_follow_ups(self, answer: str) -> List[str]:
        """Extract suggested follow-up questions."""
        # Would parse the answer for suggestions
        return []
```

---

### 3. Context Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONTEXT HIERARCHY                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    WALKTHROUGH CONTEXT                               │    │
│  │  • Title: "Understanding the Write Path"                            │    │
│  │  • Overview: "How data flows from Put() to disk"                    │    │
│  │  • Total steps: 7                                                    │    │
│  │  • Overview flow diagram                                             │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                      │    │
│  │  ┌───────────────────────────────────────────────────────────┐      │    │
│  │  │                 STEP CONTEXT (Current)                     │      │    │
│  │  │  • Step 3: "Write Batching: DBImpl::Write()"              │      │    │
│  │  │  • File: db/db_impl.cc (lines 141-185)                    │      │    │
│  │  │  • Code: (actual source code)                              │      │    │
│  │  │  • Explanation: (pre-generated explanation)                │      │    │
│  │  │  • Flow diagram: (step-specific diagram)                   │      │    │
│  │  │  • Data structures: [Writer, WriteBatch]                   │      │    │
│  │  ├───────────────────────────────────────────────────────────┤      │    │
│  │  │                                                            │      │    │
│  │  │  ┌─────────────────────────────────────────────────┐      │      │    │
│  │  │  │           Q&A HISTORY (This Step)                │      │      │    │
│  │  │  │  Q1: "What is the mutex protecting?"            │      │      │    │
│  │  │  │  A1: "The mutex protects writers_ queue..."     │      │      │    │
│  │  │  │  Q2: "Why use condition variables here?"        │      │      │    │
│  │  │  │  A2: "Condition variables allow writers..."     │      │      │    │
│  │  │  └─────────────────────────────────────────────────┘      │      │    │
│  │  │                                                            │      │    │
│  │  └───────────────────────────────────────────────────────────┘      │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  NOTE: Q&A history resets when moving to a new step                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Context Reset Policy:**
- Q&A history is cleared when the user moves to a new step
- Walkthrough context persists throughout the session
- Step context is updated when navigating between steps

**Reset Enforcement (TUI):**
- Track the current step id in UI state; when it changes, clear `qa_history`, `qa_response`, `qa_input`, and exit `qa_mode`.

---

### 4. CLI Integration

Simple input detection: if user presses Enter without input, continue to next step.

```python
class CodeWalkerAgent:
    """Extended with Q&A support."""

    def __init__(self, repo_path: str, model: str = "claude-sonnet-4-20250514"):
        # ... existing init ...
        self.tutor = CodeTutorAgent(repo_path, model)

    def _present_step(self, step_data: Dict):
        """Present a single walk step with Q&A support."""
        # ... existing step presentation code ...

        # Build tutor context
        tutor_context = TutorContext(
            step_title=step_data["title"],
            step_number=step_data["step_number"],
            file_path=step_data["file_path"],
            start_line=step_data.get("start_line", 1),
            end_line=step_data.get("end_line", 100),
            code=code,
            explanation=explanation,
            flow_diagram=step_data.get("flow"),
            walkthrough_title=self.state.plan.title,
            walkthrough_overview=self.state.plan.overview,
            total_steps=len(self._raw_plan_steps),
            qa_history=[],
        )

        # Interactive Q&A loop
        self._interactive_qa_loop(tutor_context)

    def _interactive_qa_loop(self, context: TutorContext):
        """Run the interactive Q&A loop for a step."""
        while True:
            # Prompt for input
            print()
            user_input = input("Press Enter to continue, or ask a question: ").strip()

            if not user_input:
                # Empty input = continue to next step
                break

            # Answer the question
            print("\n" + "─" * 60)
            print("🎓 Tutor:")
            print()

            response = self.tutor.answer_question(user_input, context)
            print(response.answer)

            # Show follow-up suggestions if any
            if response.follow_up_suggestions:
                print()
                print("💡 You might also want to ask:")
                for suggestion in response.follow_up_suggestions[:3]:
                    print(f"   • {suggestion}")

            print("─" * 60)

            # Add to history for context in next question
            context.qa_history.append({
                "question": user_input,
                "answer": response.answer,
            })
```

**CLI Flow Example:**

```
## Step 3: Write Batching: DBImpl::Write()
📁 db/db_impl.cc

```cpp
 141 | Status DBImpl::Write(const WriteOptions& options,
 142 |                      WriteBatch* updates) {
 143 |   Writer w(&mutex_);
 ...
```

### 💡 Explanation

This is where the write batching magic happens...

➡️ **Next:** Writing to the write-ahead log

Press Enter to continue, or ask a question: What happens if two threads call Write at the same time?

────────────────────────────────────────────────────────────
🎓 Tutor:

When two threads call Write() simultaneously, they both join the writers_ queue
(line 151). The key insight is the leader election pattern:

1. Thread A arrives first, gets added to queue, becomes the "leader" (front)
2. Thread B arrives, gets added to queue, waits on its condition variable (line 156)
3. Thread A (leader) processes both writes in a single batch
4. Thread A signals Thread B that its write is done (sets w.done = true)
5. Thread B wakes up, sees done=true, returns the status (line 160)

This batching dramatically reduces lock contention and WAL sync overhead under
concurrent load.

💡 You might also want to ask:
   • How does the leader know to include Thread B's batch?
   • What happens if the leader fails mid-write?
────────────────────────────────────────────────────────────

Press Enter to continue, or ask a question:

[Press Enter for next step...]
```

---

### 5. TUI Integration

Add a chat-style input area at the bottom of the terminal UI.

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
│  ...                                       │  ...                                   │
│                                            │                                        │
├────────────────────────────────────────────┴────────────────────────────────────────┤
│  📦 Data Structures: Writer, WriteBatch  [d]                                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  Path: Put() → Write() → [MakeRoom] → WAL → Memtable                                │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │ 🎓 Tutor: The mutex protects the writers_ queue. When multiple threads     │   │
│  │    call Write(), they all join this queue and the leader (front of queue)  │   │
│  │    batches their writes together for efficiency.                            │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │ Ask a question: █                                                           │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  [←] Prev  [→] Next  [Tab] Focus  [Enter] Send  [Esc] Clear  [q] Quit              │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Layout Changes:**

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              UPDATED LAYOUT                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  BEFORE (existing):                      AFTER (with Q&A):                          │
│  ┌───────────────────────┐               ┌───────────────────────┐                  │
│  │ Header (3 lines)      │               │ Header (3 lines)      │                  │
│  ├───────────────────────┤               ├───────────────────────┤                  │
│  │                       │               │                       │                  │
│  │ Main Content          │               │ Main Content          │                  │
│  │ (Code + Explanation)  │               │ (Code + Explanation)  │                  │
│  │                       │               │ (reduced height)      │                  │
│  │                       │               │                       │                  │
│  ├───────────────────────┤               ├───────────────────────┤                  │
│  │ Data Structures (5)   │               │ Data Structures (3)   │                  │
│  ├───────────────────────┤               ├───────────────────────┤                  │
│  │ Breadcrumb (3)        │               │ Breadcrumb (3)        │                  │
│  ├───────────────────────┤               ├───────────────────────┤                  │
│  │ Footer (3)            │               │ Chat Response (5)     │ ◄── NEW         │
│  └───────────────────────┘               ├───────────────────────┤                  │
│                                          │ Chat Input (3)        │ ◄── NEW         │
│                                          ├───────────────────────┤                  │
│                                          │ Footer (3)            │                  │
│                                          └───────────────────────┘                  │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Layout Notes (small terminals):**
- Maintain a minimum main content height and shrink optional sections in order: Q&A response → Data Structures → Breadcrumb.
- Never allow the computed main area to go negative; clamp to a safe minimum.

**TUI Implementation:**

```python
from concurrent.futures import ThreadPoolExecutor, Future

@dataclass
class UIState:
    """Extended with Q&A state."""
    # ... existing fields ...

    # Q&A state
    qa_mode: bool = False           # Whether input is focused
    qa_input: str = ""              # Current input text
    qa_cursor: int = 0              # Cursor position
    qa_response: str = ""           # Current tutor response
    qa_history: List[Dict] = field(default_factory=list)
    qa_loading: bool = False        # Whether waiting for response
    qa_future: Optional[Future] = None  # Background request handle
    qa_pending_question: Optional[str] = None  # Track submitted question
    current_step_id: Optional[str] = None  # For step-change resets


def _render_screen(stdscr, state: UIState, height: int, width: int) -> None:
    """Updated render with Q&A components."""
    # Calculate layout
    header_h = 1
    footer_h = 1
    qa_input_h = 3 if state.qa_mode or state.qa_response else 1
    qa_response_h = min(5, len(state.qa_response.split('\n')) + 2) if state.qa_response else 0
    breadcrumb_h = 1 if state.show_breadcrumb else 0
    data_h = 3 if state.data_structures_expanded else 1

    min_main_h = 4
    available = height - header_h - footer_h
    overflow = (min_main_h + qa_input_h + qa_response_h + breadcrumb_h + data_h) - available
    if overflow > 0:
        shrink = min(overflow, qa_response_h)
        qa_response_h -= shrink
        overflow -= shrink
    if overflow > 0 and data_h > 1:
        shrink = min(overflow, data_h - 1)
        data_h -= shrink
        overflow -= shrink
    if overflow > 0 and breadcrumb_h == 1:
        breadcrumb_h = 0
        overflow -= 1

    main_h = max(min_main_h, available - qa_input_h - qa_response_h - breadcrumb_h - data_h)

    # Render components
    _render_header(stdscr, state, 0, width)
    _render_main(stdscr, state, header_h, main_h, width)
    _render_data_structures(stdscr, state, header_h + main_h, data_h, width)
    _render_breadcrumb(stdscr, state, header_h + main_h + data_h, width)

    # NEW: Render Q&A components
    qa_y = header_h + main_h + data_h + breadcrumb_h
    if state.qa_response:
        _render_qa_response(stdscr, state, qa_y, qa_response_h, width)
        qa_y += qa_response_h
    _render_qa_input(stdscr, state, qa_y, qa_input_h, width)

    _render_footer(stdscr, state, height - 1, width)


def _render_qa_response(stdscr, state: UIState, y: int, height: int, width: int) -> None:
    """Render the tutor's response."""
    _draw_box(stdscr, y, 0, height, width, title="🎓 Tutor")

    lines = state.qa_response.split('\n')
    for i, line in enumerate(lines[:height - 2]):
        _safe_addstr(stdscr, y + 1 + i, 1, _truncate(line, width - 2))


def _render_qa_input(stdscr, state: UIState, y: int, height: int, width: int) -> None:
    """Render the Q&A input box."""
    if state.qa_loading:
        title = "Thinking..."
    else:
        title = "Ask a question (Enter to send, Esc to cancel)"

    _draw_box(stdscr, y, 0, height, width, title=title)

    # Render input text with cursor
    input_text = state.qa_input
    if state.qa_mode:
        # Show cursor
        before = input_text[:state.qa_cursor]
        after = input_text[state.qa_cursor:]
        display = before + "█" + after
    else:
        display = input_text if input_text else "(Press ? to ask a question)"

    attr = curses.A_NORMAL if state.qa_mode else curses.A_DIM
    _safe_addstr(stdscr, y + 1, 1, _truncate(display, width - 2), attr)


def _handle_qa_input(state: UIState, key: int) -> Optional[str]:
    """
    Handle keyboard input for Q&A mode.

    Returns:
        The question to submit, or None if still editing
    """
    if key == 27:  # Escape
        state.qa_mode = False
        state.qa_input = ""
        state.qa_cursor = 0
        return None

    elif key == 10:  # Enter
        if state.qa_input.strip():
            question = state.qa_input.strip()
            state.qa_input = ""
            state.qa_cursor = 0
            return question
        else:
            state.qa_mode = False
            return None

    elif key == curses.KEY_BACKSPACE or key == 127:
        if state.qa_cursor > 0:
            state.qa_input = (
                state.qa_input[:state.qa_cursor - 1] +
                state.qa_input[state.qa_cursor:]
            )
            state.qa_cursor -= 1

    elif key == curses.KEY_LEFT:
        state.qa_cursor = max(0, state.qa_cursor - 1)

    elif key == curses.KEY_RIGHT:
        state.qa_cursor = min(len(state.qa_input), state.qa_cursor + 1)

    elif key == curses.KEY_HOME:
        state.qa_cursor = 0

    elif key == curses.KEY_END:
        state.qa_cursor = len(state.qa_input)

    elif 32 <= key < 127:  # Printable characters
        char = chr(key)
        state.qa_input = (
            state.qa_input[:state.qa_cursor] +
            char +
            state.qa_input[state.qa_cursor:]
        )
        state.qa_cursor += 1

    return None


def _run_ui(stdscr, session: WalkSession, agent: CodeWalkerAgent, debug: bool) -> None:
    """Updated main loop with Q&A support."""
    # ... existing setup ...

    state = UIState(session=session, agent=agent, debug=debug)
    tutor = CodeTutorAgent(agent.tools.repo_path)
    executor = ThreadPoolExecutor(max_workers=1)

    while True:
        # ... existing render code ...
        # Reset Q&A state on step change
        step_id = session.current_step_id
        if state.current_step_id != step_id:
            state.current_step_id = step_id
            state.qa_history = []
            state.qa_response = ""
            state.qa_input = ""
            state.qa_mode = False
            state.qa_future = None
            state.qa_loading = False
            state.qa_pending_question = None

        key = stdscr.getch()

        # Collect async response if ready
        if state.qa_loading and state.qa_future and state.qa_future.done():
            response = state.qa_future.result()
            state.qa_loading = False
            state.qa_future = None
            state.qa_response = response.answer
            state.qa_history.append({
                "question": state.qa_pending_question or "",
                "answer": response.answer,
            })
            state.qa_pending_question = None

        if state.qa_mode:
            # Handle Q&A input
            question = _handle_qa_input(state, key)

            if question:
                # Show loading state
                state.qa_loading = True
                _render_screen(stdscr, state, height, width)
                stdscr.refresh()

                # Build context and get answer
                context = _build_tutor_context(state, session)
                state.qa_pending_question = question
                state.qa_future = executor.submit(tutor.answer_question, question, context)
        else:
            # Existing key handling
            if key == ord('?') or key == ord('/'):
                state.qa_mode = True
            elif key == ord('c'):
                state.qa_response = ""
            elif key == ord('q'):
                break
            # ... rest of existing handlers ...
```

---

### 6. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           SYSTEM ARCHITECTURE                                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌─────────────────┐                                                                │
│  │   User Input    │                                                                │
│  │  (CLI or TUI)   │                                                                │
│  └────────┬────────┘                                                                │
│           │                                                                          │
│           ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐                │
│  │                      INPUT HANDLER                               │                │
│  │  • Detects empty input (continue) vs question                   │                │
│  │  • Passes question to CodeTutorAgent                            │                │
│  └─────────────────────────────────────────────────────────────────┘                │
│           │                                                                          │
│           ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐                │
│  │                     CodeTutorAgent                               │                │
│  │  ┌─────────────────────────────────────────────────────────┐    │                │
│  │  │                   SYSTEM PROMPT                          │    │                │
│  │  │  • Walkthrough context (title, overview)                │    │                │
│  │  │  • Step context (code, explanation, flow)               │    │                │
│  │  │  • Teaching guidelines                                   │    │                │
│  │  └─────────────────────────────────────────────────────────┘    │                │
│  │                          │                                       │                │
│  │                          ▼                                       │                │
│  │  ┌─────────────────────────────────────────────────────────┐    │                │
│  │  │                   TOOL EXECUTION                         │    │                │
│  │  │  • read_file      → CodeWalkerTools.read_file           │    │                │
│  │  │  • search_code    → CodeWalkerTools.grep                │    │                │
│  │  │  • find_definition → CodeWalkerTools.find_definition    │    │                │
│  │  │  • find_usages    → CodeWalkerTools.find_usages         │    │                │
│  │  └─────────────────────────────────────────────────────────┘    │                │
│  │                          │                                       │                │
│  │                          ▼                                       │                │
│  │  ┌─────────────────────────────────────────────────────────┐    │                │
│  │  │                   RESPONSE                               │    │                │
│  │  │  • Answer text                                          │    │                │
│  │  │  • References (files, symbols)                          │    │                │
│  │  │  • Follow-up suggestions                                │    │                │
│  │  └─────────────────────────────────────────────────────────┘    │                │
│  └─────────────────────────────────────────────────────────────────┘                │
│           │                                                                          │
│           ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐                │
│  │                     OUTPUT HANDLER                               │                │
│  │  • Formats response for CLI or TUI                              │                │
│  │  • Updates Q&A history in context                               │                │
│  │  • Returns to input prompt                                      │                │
│  └─────────────────────────────────────────────────────────────────┘                │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 7. Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA FLOW                                               │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  1. USER ASKS QUESTION                                                              │
│     ┌─────────────────────────────────────────────────────────────────────┐         │
│     │ "What does the mutex protect?"                                      │         │
│     └─────────────────────────────────────────────────────────────────────┘         │
│                              │                                                       │
│                              ▼                                                       │
│  2. BUILD TUTOR CONTEXT                                                             │
│     ┌─────────────────────────────────────────────────────────────────────┐         │
│     │ TutorContext(                                                       │         │
│     │   step_title="Write Batching: DBImpl::Write()",                    │         │
│     │   code="Status DBImpl::Write(...)...",                             │         │
│     │   explanation="This is where batching magic happens...",           │         │
│     │   qa_history=[],                                                    │         │
│     │ )                                                                   │         │
│     └─────────────────────────────────────────────────────────────────────┘         │
│                              │                                                       │
│                              ▼                                                       │
│  3. LLM CALL                                                                        │
│     ┌─────────────────────────────────────────────────────────────────────┐         │
│     │ System: "You are a code tutor... [context]"                        │         │
│     │ User: "What does the mutex protect?"                               │         │
│     │                                                                     │         │
│     │ [Model may use tools: read_file, search_code, etc.]                │         │
│     └─────────────────────────────────────────────────────────────────────┘         │
│                              │                                                       │
│                              ▼                                                       │
│  4. RESPONSE                                                                        │
│     ┌─────────────────────────────────────────────────────────────────────┐         │
│     │ TutorResponse(                                                      │         │
│     │   answer="The mutex (mutex_) protects the writers_ queue...",      │         │
│     │   references=["db/db_impl.cc:150"],                                │         │
│     │   follow_up_suggestions=["How does leader election work?"],        │         │
│     │ )                                                                   │         │
│     └─────────────────────────────────────────────────────────────────────┘         │
│                              │                                                       │
│                              ▼                                                       │
│  5. UPDATE CONTEXT                                                                  │
│     ┌─────────────────────────────────────────────────────────────────────┐         │
│     │ context.qa_history.append({                                         │         │
│     │   "question": "What does the mutex protect?",                      │         │
│     │   "answer": "The mutex (mutex_) protects...",                      │         │
│     │ })                                                                  │         │
│     └─────────────────────────────────────────────────────────────────────┘         │
│                              │                                                       │
│                              ▼                                                       │
│  6. DISPLAY & WAIT FOR NEXT INPUT                                                   │
│     ┌─────────────────────────────────────────────────────────────────────┐         │
│     │ 🎓 Tutor:                                                          │         │
│     │ The mutex (mutex_) protects the writers_ queue (line 151)...       │         │
│     │                                                                     │         │
│     │ Ask a question: █                                                   │         │
│     └─────────────────────────────────────────────────────────────────────┘         │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 8. Keyboard Shortcuts (TUI)

| Key | Action | Context |
|-----|--------|---------|
| `?` | Enter Q&A mode | Normal mode |
| `Enter` | Send question | Q&A input mode |
| `Esc` | Cancel/clear input | Q&A input mode |
| `←/→` | Move cursor | Q&A input mode |
| `Backspace` | Delete character | Q&A input mode |
| `c` | Clear response | Normal mode |

---

### 9. Future Enhancements

1. **Conversation Export**: Save Q&A history to markdown alongside walkthrough
2. **Voice Input**: Speech-to-text for questions (accessibility)
3. **Code Highlighting**: Highlight referenced lines in code panel when tutor mentions them
4. **Smart Suggestions**: Proactively suggest questions based on code patterns
5. **Multi-step Context**: Option to include previous steps' Q&A in context
6. **Bookmarks**: Save interesting Q&A exchanges for later reference
