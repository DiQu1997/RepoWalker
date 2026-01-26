You're right - let's make this practical and buildable. A simple ReAct-style agent with a focused tool set and clear loop.

## Simple Code Walker Agent Design

### 1. Core Loop

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AGENT LOOP (Simple)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────┐                                                      │
│   │ User Request │  "I want to understand how writes work in this DB"   │
│   └──────┬───────┘                                                      │
│          │                                                               │
│          ▼                                                               │
│   ┌──────────────┐                                                      │
│   │   EXPLORE    │  ◄─────────────────────────────────┐                 │
│   │    PHASE     │                                    │                 │
│   │              │  • tree, read README, grep         │                 │
│   └──────┬───────┘                                    │                 │
│          │                                            │                 │
│          ▼                                            │                 │
│   ┌──────────────┐      Need more info?              │                 │
│   │    THINK     │ ─────────YES──────────────────────┘                 │
│   │              │                                                      │
│   └──────┬───────┘                                                      │
│          │ NO - Ready to plan                                           │
│          ▼                                                               │
│   ┌──────────────┐                                                      │
│   │     PLAN     │  Generate ordered walk-through steps                 │
│   │    PHASE     │                                                      │
│   └──────┬───────┘                                                      │
│          │                                                               │
│          ▼                                                               │
│   ┌──────────────┐                                                      │
│   │    WALK      │  Present each step with full context                 │
│   │    PHASE     │  Code + Data Structures + Explanation                │
│   └──────────────┘                                                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Complete Tool Set

```python
from dataclasses import dataclass
from typing import Literal, Optional, List
from pathlib import Path
import subprocess

@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None

class CodeWalkerTools:
    """All tools available to the agent."""
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self._validate_repo()
    
    # ========== FILE SYSTEM TOOLS ==========
    
    def tree(self, path: str = ".", max_depth: int = 3, 
             include_hidden: bool = False) -> ToolResult:
        """
        Show directory structure.
        
        Use when: Starting exploration, understanding project layout.
        """
        target = self._resolve_path(path)
        cmd = ["tree", "-L", str(max_depth), "--noreport"]
        if not include_hidden:
            cmd.append("-I")
            cmd.append("__pycache__|node_modules|.git|*.pyc|.venv|venv")
        cmd.append(str(target))
        
        return self._run(cmd)
    
    def read_file(self, path: str, start_line: int = None, 
                  end_line: int = None) -> ToolResult:
        """
        Read file contents, optionally a specific line range.
        
        Use when: Need to see actual code, README, config files.
        """
        target = self._resolve_path(path)
        
        if not target.exists():
            return ToolResult(False, "", f"File not found: {path}")
        
        if not target.is_file():
            return ToolResult(False, "", f"Not a file: {path}")
        
        try:
            content = target.read_text()
            lines = content.split('\n')
            
            # Add line numbers
            if start_line is not None or end_line is not None:
                start = (start_line or 1) - 1
                end = end_line or len(lines)
                lines = lines[start:end]
                numbered = [f"{i+start+1:4d} | {line}" 
                           for i, line in enumerate(lines)]
            else:
                numbered = [f"{i+1:4d} | {line}" 
                           for i, line in enumerate(lines)]
            
            return ToolResult(True, '\n'.join(numbered))
        except Exception as e:
            return ToolResult(False, "", str(e))
    
    def list_dir(self, path: str = ".") -> ToolResult:
        """
        List directory contents with file types and sizes.
        
        Use when: Quick look at a specific directory.
        """
        target = self._resolve_path(path)
        cmd = ["ls", "-la", str(target)]
        return self._run(cmd)
    
    def file_info(self, path: str) -> ToolResult:
        """
        Get file metadata: size, type, last modified.
        
        Use when: Need to understand what kind of file something is.
        """
        target = self._resolve_path(path)
        cmd = ["file", str(target)]
        result = self._run(cmd)
        
        if result.success:
            # Add size and modification time
            stat = target.stat()
            result.output += f"\nSize: {stat.st_size} bytes"
            result.output += f"\nModified: {stat.st_mtime}"
        
        return result
    
    # ========== SEARCH TOOLS ==========
    
    def grep(self, pattern: str, path: str = ".", 
             file_pattern: str = None, context_lines: int = 2,
             ignore_case: bool = False) -> ToolResult:
        """
        Search for pattern in files.
        
        Use when: Looking for specific function names, variables, 
                  strings, imports, class definitions.
        """
        target = self._resolve_path(path)
        
        cmd = ["grep", "-rn", f"-C{context_lines}"]
        if ignore_case:
            cmd.append("-i")
        
        # Exclude common non-code directories
        cmd.extend(["--exclude-dir=.git", "--exclude-dir=node_modules",
                    "--exclude-dir=__pycache__", "--exclude-dir=.venv",
                    "--exclude-dir=venv", "--exclude-dir=target",
                    "--exclude-dir=build", "--exclude-dir=dist"])
        
        if file_pattern:
            cmd.extend(["--include", file_pattern])
        
        cmd.extend([pattern, str(target)])
        
        return self._run(cmd, allow_empty=True)
    
    def git_grep(self, pattern: str, file_pattern: str = None) -> ToolResult:
        """
        Search tracked files using git grep (faster, respects .gitignore).
        
        Use when: Searching in a git repo, want clean results.
        """
        cmd = ["git", "-C", str(self.repo_path), "grep", "-n", "--heading"]
        
        if file_pattern:
            cmd.extend(["--", file_pattern])
        
        cmd.append(pattern)
        
        return self._run(cmd, allow_empty=True)
    
    def find_files(self, name_pattern: str, file_type: str = "f") -> ToolResult:
        """
        Find files by name pattern.
        
        Use when: Looking for specific files like "config", "main", 
                  "handler", schema files, etc.
        
        Args:
            name_pattern: glob pattern like "*.proto" or "*config*"
            file_type: "f" for files, "d" for directories
        """
        cmd = ["find", str(self.repo_path), 
               "-type", file_type,
               "-name", name_pattern,
               "-not", "-path", "*/.git/*",
               "-not", "-path", "*/node_modules/*",
               "-not", "-path", "*/__pycache__/*"]
        
        return self._run(cmd, allow_empty=True)
    
    def find_definition(self, symbol: str, language: str = None) -> ToolResult:
        """
        Find where a function/class/type is defined.
        
        Use when: You see a function call and need to find its implementation.
        """
        # Build language-aware patterns
        patterns = {
            "python": [
                f"def {symbol}\\(",
                f"class {symbol}[:(]",
                f"^{symbol}\\s*=",  # Variable assignment
            ],
            "go": [
                f"func {symbol}\\(",
                f"func \\([^)]+\\) {symbol}\\(",  # Method
                f"type {symbol} ",
            ],
            "javascript": [
                f"function {symbol}\\(",
                f"const {symbol}\\s*=",
                f"class {symbol}",
                f"{symbol}\\s*:\\s*function",
            ],
            "java": [
                f"class {symbol}",
                f"interface {symbol}",
                f"\\s+{symbol}\\s*\\(",  # Method definition
            ],
            "rust": [
                f"fn {symbol}\\(",
                f"struct {symbol}",
                f"enum {symbol}",
                f"impl {symbol}",
            ],
            "cpp": [
                f"class {symbol}",
                f"struct {symbol}",
                f"\\s+{symbol}\\s*\\(",
            ],
        }
        
        if language and language in patterns:
            search_patterns = patterns[language]
        else:
            # Try all patterns
            search_patterns = []
            for lang_patterns in patterns.values():
                search_patterns.extend(lang_patterns)
        
        results = []
        for pattern in search_patterns:
            result = self.grep(pattern, context_lines=3)
            if result.success and result.output:
                results.append(result.output)
        
        if results:
            return ToolResult(True, "\n---\n".join(results))
        else:
            return ToolResult(True, f"No definition found for: {symbol}")
    
    def find_usages(self, symbol: str) -> ToolResult:
        """
        Find all usages of a symbol (function calls, references).
        
        Use when: Understanding how/where something is used.
        """
        return self.grep(symbol, context_lines=1)
    
    # ========== CODE ANALYSIS TOOLS ==========
    
    def get_function(self, file_path: str, function_name: str) -> ToolResult:
        """
        Extract a complete function/method from a file.
        
        Use when: Need to see full implementation of a specific function.
        """
        result = self.read_file(file_path)
        if not result.success:
            return result
        
        # Simple extraction - find function start and track indentation
        lines = result.output.split('\n')
        in_function = False
        function_lines = []
        base_indent = 0
        
        for line in lines:
            # Remove line number prefix for analysis
            if ' | ' in line:
                line_num, code = line.split(' | ', 1)
            else:
                line_num, code = "", line
            
            # Check for function definition
            if not in_function:
                if self._is_function_def(code, function_name):
                    in_function = True
                    base_indent = len(code) - len(code.lstrip())
                    function_lines.append(line)
            else:
                # Check if we've exited the function
                stripped = code.strip()
                if stripped and not code.startswith(' ' * (base_indent + 1)) and \
                   not stripped.startswith('#') and not stripped.startswith('//'):
                    # Check if it's a new definition at same or lower indent
                    current_indent = len(code) - len(code.lstrip())
                    if current_indent <= base_indent and self._is_new_definition(code):
                        break
                function_lines.append(line)
        
        if function_lines:
            return ToolResult(True, '\n'.join(function_lines))
        else:
            return ToolResult(False, "", f"Function not found: {function_name}")
    
    def get_class(self, file_path: str, class_name: str) -> ToolResult:
        """
        Extract a complete class definition.
        
        Use when: Need to see a data structure, its fields and methods.
        """
        # Similar logic to get_function but for classes
        result = self.read_file(file_path)
        if not result.success:
            return result
        
        lines = result.output.split('\n')
        in_class = False
        class_lines = []
        base_indent = 0
        
        for line in lines:
            if ' | ' in line:
                line_num, code = line.split(' | ', 1)
            else:
                line_num, code = "", line
            
            if not in_class:
                if f"class {class_name}" in code or \
                   f"struct {class_name}" in code or \
                   f"type {class_name}" in code:
                    in_class = True
                    base_indent = len(code) - len(code.lstrip())
                    class_lines.append(line)
            else:
                stripped = code.strip()
                if stripped:
                    current_indent = len(code) - len(code.lstrip())
                    if current_indent <= base_indent and \
                       (code.strip().startswith('class ') or 
                        code.strip().startswith('def ') or
                        code.strip().startswith('func ') or
                        code.strip().startswith('type ')):
                        break
                class_lines.append(line)
        
        if class_lines:
            return ToolResult(True, '\n'.join(class_lines))
        else:
            return ToolResult(False, "", f"Class not found: {class_name}")
    
    def get_imports(self, file_path: str) -> ToolResult:
        """
        Get all imports/includes from a file.
        
        Use when: Understanding dependencies, what modules are used.
        """
        result = self.read_file(file_path)
        if not result.success:
            return result
        
        import_patterns = [
            r'^import ',
            r'^from .* import',
            r'^#include',
            r'^require\(',
            r'^const .* = require\(',
            r'^use ',
        ]
        
        imports = []
        for line in result.output.split('\n'):
            if ' | ' in line:
                _, code = line.split(' | ', 1)
            else:
                code = line
            
            for pattern in import_patterns:
                import re
                if re.match(pattern, code.strip()):
                    imports.append(line)
                    break
        
        return ToolResult(True, '\n'.join(imports) if imports else "No imports found")
    
    def get_outline(self, file_path: str) -> ToolResult:
        """
        Get structural outline of a file (classes, functions, methods).
        
        Use when: Quick overview of what's in a file without reading all code.
        """
        result = self.read_file(file_path)
        if not result.success:
            return result
        
        outline = []
        current_class = None
        
        for line in result.output.split('\n'):
            if ' | ' in line:
                line_num, code = line.split(' | ', 1)
                line_num = line_num.strip()
            else:
                continue
            
            stripped = code.strip()
            indent = len(code) - len(code.lstrip())
            
            # Detect class/struct/type definitions
            if any(stripped.startswith(kw) for kw in 
                   ['class ', 'struct ', 'type ', 'interface ']):
                current_class = stripped.split()[1].split('(')[0].split(':')[0]
                outline.append(f"L{line_num}: {stripped}")
            
            # Detect function/method definitions
            elif any(stripped.startswith(kw) for kw in ['def ', 'func ', 'fn ']):
                prefix = "  " if indent > 0 else ""
                outline.append(f"L{line_num}: {prefix}{stripped.split(':')[0]}")
            
            # Detect JavaScript/Java style methods
            elif '(' in stripped and '):' in stripped or ') {' in stripped:
                if not any(stripped.startswith(kw) for kw in 
                          ['if', 'for', 'while', 'switch', 'catch']):
                    prefix = "  " if indent > 0 else ""
                    outline.append(f"L{line_num}: {prefix}{stripped}")
        
        return ToolResult(True, '\n'.join(outline) if outline else "No outline available")
    
    # ========== GIT TOOLS ==========
    
    def git_log(self, path: str = None, n: int = 10) -> ToolResult:
        """
        Show recent commit history, optionally for a specific file.
        
        Use when: Understanding recent changes, who worked on code.
        """
        cmd = ["git", "-C", str(self.repo_path), "log", 
               f"-{n}", "--oneline", "--date=short",
               "--format=%h %ad %s"]
        if path:
            cmd.extend(["--", path])
        
        return self._run(cmd)
    
    def git_show(self, commit: str, file_path: str = None) -> ToolResult:
        """
        Show what changed in a specific commit.
        
        Use when: Understanding a specific change in detail.
        """
        cmd = ["git", "-C", str(self.repo_path), "show", 
               "--stat", commit]
        if file_path:
            cmd.extend(["--", file_path])
        
        return self._run(cmd)
    
    def git_blame(self, file_path: str, start_line: int = None, 
                  end_line: int = None) -> ToolResult:
        """
        Show who last modified each line.
        
        Use when: Understanding authorship, when code was added.
        """
        cmd = ["git", "-C", str(self.repo_path), "blame"]
        if start_line and end_line:
            cmd.extend([f"-L{start_line},{end_line}"])
        cmd.append(file_path)
        
        return self._run(cmd)
    
    # ========== HELPER METHODS ==========
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to repo root."""
        if Path(path).is_absolute():
            return Path(path)
        return self.repo_path / path
    
    def _run(self, cmd: List[str], allow_empty: bool = False) -> ToolResult:
        """Run a shell command and return result."""
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=30,
                cwd=self.repo_path
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output and not allow_empty:
                    return ToolResult(True, "(empty output)")
                return ToolResult(True, output)
            else:
                if allow_empty and result.returncode == 1:
                    # grep returns 1 when no matches
                    return ToolResult(True, "(no matches)")
                return ToolResult(False, "", result.stderr.strip())
                
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", "Command timed out")
        except Exception as e:
            return ToolResult(False, "", str(e))
    
    def _validate_repo(self):
        """Ensure repo path exists."""
        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {self.repo_path}")
    
    def _is_function_def(self, code: str, name: str) -> bool:
        """Check if line is a function definition."""
        patterns = [
            f"def {name}(",
            f"func {name}(",
            f"fn {name}(",
            f"function {name}(",
        ]
        return any(p in code for p in patterns)
    
    def _is_new_definition(self, code: str) -> bool:
        """Check if line starts a new definition."""
        keywords = ['def ', 'class ', 'func ', 'fn ', 'type ', 'struct ']
        stripped = code.strip()
        return any(stripped.startswith(kw) for kw in keywords)
```

---

### 3. Agent State & Types

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Literal
from enum import Enum

class Phase(Enum):
    EXPLORE = "explore"      # Gathering information
    PLAN = "plan"            # Creating walk-through plan  
    WALK = "walk"            # Presenting steps to user
    COMPLETE = "complete"

@dataclass
class WalkStep:
    """One step in the code walk-through."""
    step_number: int
    title: str                    # e.g., "Entry Point: write_api()"
    file_path: str
    start_line: int
    end_line: int
    code: str                     # The actual code
    explanation: str              # Detailed explanation
    data_structures: List[str]    # Related types/structs to show
    key_concepts: List[str]       # Algorithms, patterns to explain
    next_step_hint: str           # Why we go to the next step

@dataclass
class WalkPlan:
    """The complete walk-through plan."""
    title: str                    # e.g., "Understanding the Write Path"
    overview: str                 # High-level summary
    steps: List[WalkStep]
    total_steps: int

@dataclass
class ExplorationContext:
    """What the agent has learned during exploration."""
    repo_structure: Optional[str] = None
    readme_content: Optional[str] = None
    key_files: List[str] = field(default_factory=list)
    entry_points: List[Dict] = field(default_factory=list)
    relevant_searches: List[Dict] = field(default_factory=list)
    data_structures_found: List[Dict] = field(default_factory=list)

@dataclass  
class AgentState:
    """Complete agent state."""
    user_request: str
    repo_path: str
    phase: Phase = Phase.EXPLORE
    exploration: ExplorationContext = field(default_factory=ExplorationContext)
    plan: Optional[WalkPlan] = None
    current_step: int = 0
    thinking_history: List[Dict] = field(default_factory=list)
    tool_calls: List[Dict] = field(default_factory=list)
```

---

### 4. The Agent Loop

```python
from anthropic import Anthropic

class CodeWalkerAgent:
    """Simple agent with explore -> plan -> walk loop."""
    
    def __init__(self, repo_path: str, model: str = "claude-sonnet-4-20250514"):
        self.tools = CodeWalkerTools(repo_path)
        self.client = Anthropic()
        self.model = model
        self.state: Optional[AgentState] = None
    
    def run(self, user_request: str) -> None:
        """Main entry point - run the full agent loop."""
        self.state = AgentState(
            user_request=user_request,
            repo_path=str(self.tools.repo_path)
        )
        
        print(f"\n🎯 Goal: {user_request}\n")
        print("=" * 60)
        
        # Phase 1: Explore
        self._explore_phase()
        
        # Phase 2: Plan
        self._plan_phase()
        
        # Phase 3: Walk
        self._walk_phase()
    
    # ========== PHASE 1: EXPLORE ==========
    
    def _explore_phase(self):
        """Gather information about the codebase."""
        print("\n📂 EXPLORATION PHASE\n")
        self.state.phase = Phase.EXPLORE
        
        max_iterations = 25
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            print(f"--- Thinking (iteration {iteration}) ---")
            
            # Ask LLM what to do next
            action = self._get_next_exploration_action()
            
            if action["type"] == "done":
                print("\n✅ Exploration complete. Ready to plan.\n")
                break
            
            elif action["type"] == "tool":
                # Execute the tool
                result = self._execute_tool(action["tool"], action["args"])
                
                # Record the result
                self.state.tool_calls.append({
                    "tool": action["tool"],
                    "args": action["args"],
                    "result_preview": result.output[:500] if result.success else result.error
                })
                
                # Store relevant findings
                self._update_exploration_context(action, result)
        
        if iteration >= max_iterations:
            print("\n⚠️ Max iterations reached. Proceeding with available info.\n")
    
    def _get_next_exploration_action(self) -> Dict:
        """Ask LLM what to explore next."""
        
        prompt = f"""You are exploring a codebase to understand: "{self.state.user_request}"

## What You've Learned So Far

Repository: {self.state.repo_path}

{self._format_exploration_context()}

## Available Tools

1. tree(path=".", max_depth=3) - Show directory structure
2. read_file(path, start_line=None, end_line=None) - Read file contents
3. grep(pattern, path=".", file_pattern=None, context_lines=2) - Search for pattern
4. git_grep(pattern, file_pattern=None) - Search tracked files
5. find_files(name_pattern, file_type="f") - Find files by name
6. find_definition(symbol, language=None) - Find where symbol is defined
7. find_usages(symbol) - Find all usages of a symbol
8. get_function(file_path, function_name) - Extract complete function
9. get_class(file_path, class_name) - Extract complete class/struct
10. get_imports(file_path) - Get imports from a file
11. get_outline(file_path) - Get structural outline of a file
12. list_dir(path) - List directory contents

## Your Task

Decide what to do next to understand "{self.state.user_request}".

Think step by step:
1. What do I still need to understand?
2. What's the most valuable information to get next?
3. Which tool will give me that information?

If you have enough information to create a walk-through plan (you know the entry point, 
the key code path, and relevant data structures), respond with:
{{"type": "done", "reason": "why you're ready"}}

Otherwise, respond with the next tool to use:
{{"type": "tool", "tool": "tool_name", "args": {{"arg1": "value1"}}, "reason": "why this tool"}}

Respond with ONLY the JSON, no other text."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Parse JSON response
        import json
        text = response.content[0].text.strip()
        # Handle potential markdown code blocks
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        try:
            action = json.loads(text)
            print(f"Action: {action.get('tool', 'done')} - {action.get('reason', '')[:100]}")
            return action
        except json.JSONDecodeError:
            # Fallback - try to extract JSON from response
            print(f"Failed to parse: {text[:200]}")
            return {"type": "done", "reason": "parse error"}
    
    def _execute_tool(self, tool_name: str, args: Dict) -> ToolResult:
        """Execute a tool and return result."""
        print(f"  🔧 {tool_name}({args})")
        
        tool_fn = getattr(self.tools, tool_name, None)
        if not tool_fn:
            return ToolResult(False, "", f"Unknown tool: {tool_name}")
        
        try:
            result = tool_fn(**args)
            if result.success:
                preview = result.output[:200] + "..." if len(result.output) > 200 else result.output
                print(f"  ✓ {preview}")
            else:
                print(f"  ✗ {result.error}")
            return result
        except Exception as e:
            return ToolResult(False, "", str(e))
    
    def _update_exploration_context(self, action: Dict, result: ToolResult):
        """Update exploration context based on tool results."""
        if not result.success:
            return
        
        tool = action["tool"]
        ctx = self.state.exploration
        
        if tool == "tree":
            ctx.repo_structure = result.output
        
        elif tool == "read_file":
            path = action["args"].get("path", "").lower()
            if "readme" in path:
                ctx.readme_content = result.output
            elif any(x in path for x in ["config", "main", "app", "server"]):
                ctx.key_files.append({
                    "path": action["args"]["path"],
                    "preview": result.output[:500]
                })
        
        elif tool in ["grep", "git_grep", "find_definition"]:
            ctx.relevant_searches.append({
                "query": action["args"].get("pattern") or action["args"].get("symbol"),
                "results": result.output[:1000]
            })
        
        elif tool in ["get_class", "get_function"]:
            ctx.data_structures_found.append({
                "name": action["args"].get("class_name") or action["args"].get("function_name"),
                "file": action["args"]["file_path"],
                "content": result.output
            })
    
    def _format_exploration_context(self) -> str:
        """Format current exploration context for the prompt."""
        ctx = self.state.exploration
        parts = []
        
        if ctx.repo_structure:
            parts.append(f"### Directory Structure\n```\n{ctx.repo_structure[:2000]}\n```")
        
        if ctx.readme_content:
            parts.append(f"### README\n```\n{ctx.readme_content[:2000]}\n```")
        
        if ctx.key_files:
            files_text = "\n".join([f"- {f['path']}" for f in ctx.key_files])
            parts.append(f"### Key Files Found\n{files_text}")
        
        if ctx.relevant_searches:
            searches_text = "\n".join([
                f"- Search '{s['query']}': {len(s['results'])} chars of results" 
                for s in ctx.relevant_searches[-5:]  # Last 5
            ])
            parts.append(f"### Recent Searches\n{searches_text}")
        
        if ctx.data_structures_found:
            ds_text = "\n".join([f"- {d['name']} in {d['file']}" 
                                for d in ctx.data_structures_found])
            parts.append(f"### Data Structures Found\n{ds_text}")
        
        if self.state.tool_calls:
            calls_text = "\n".join([
                f"- {c['tool']}({list(c['args'].keys())})" 
                for c in self.state.tool_calls[-10:]
            ])
            parts.append(f"### Tool Call History\n{calls_text}")
        
        return "\n\n".join(parts) if parts else "(No exploration done yet)"
    
    # ========== PHASE 2: PLAN ==========
    
    def _plan_phase(self):
        """Generate the walk-through plan."""
        print("\n📋 PLANNING PHASE\n")
        self.state.phase = Phase.PLAN
        
        prompt = f"""Based on your exploration, create a detailed walk-through plan for: 
"{self.state.user_request}"

## Exploration Results

{self._format_exploration_context()}

## Full Tool Results

{self._format_full_tool_results()}

## Instructions

Create a step-by-step walk-through plan. For each step:
1. Identify the exact file and line range
2. Explain what that code does
3. Identify any data structures that need explanation
4. Explain how it connects to the next step

Respond with JSON:
{{
    "title": "Walk-through title",
    "overview": "2-3 sentence overview of the entire flow",
    "steps": [
        {{
            "step_number": 1,
            "title": "Step title (e.g., 'Entry Point: handleWrite()')",
            "file_path": "path/to/file.py",
            "function_or_section": "function name or description",
            "why_important": "Why this step matters",
            "data_structures": ["TypeA", "TypeB"],
            "key_concepts": ["concept1", "concept2"],
            "leads_to": "What this step leads to next"
        }}
    ]
}}

Include 5-10 steps covering the complete code path. Be specific about files and functions."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        import json
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        
        try:
            plan_data = json.loads(text)
            self.state.plan = WalkPlan(
                title=plan_data["title"],
                overview=plan_data["overview"],
                steps=[],
                total_steps=len(plan_data["steps"])
            )
            
            # Store raw step data for walk phase
            self._raw_plan_steps = plan_data["steps"]
            
            print(f"📖 {plan_data['title']}")
            print(f"   {plan_data['overview']}")
            print(f"   ({len(plan_data['steps'])} steps)")
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Failed to parse plan: {e}")
            print(f"Raw response: {text[:500]}")
    
    def _format_full_tool_results(self) -> str:
        """Format complete tool results for planning."""
        parts = []
        for call in self.state.tool_calls:
            parts.append(f"### {call['tool']}({call['args']})\n```\n{call['result_preview']}\n```")
        return "\n\n".join(parts)
    
    # ========== PHASE 3: WALK ==========
    
    def _walk_phase(self):
        """Present the walk-through to the user."""
        print("\n" + "=" * 60)
        print("🚶 CODE WALK-THROUGH")
        print("=" * 60)
        
        if not self.state.plan or not hasattr(self, '_raw_plan_steps'):
            print("No plan available.")
            return
        
        self.state.phase = Phase.WALK
        
        print(f"\n# {self.state.plan.title}\n")
        print(f"{self.state.plan.overview}\n")
        print("-" * 60)
        
        for i, step_data in enumerate(self._raw_plan_steps):
            self.state.current_step = i + 1
            self._present_step(step_data)
            
            if i < len(self._raw_plan_steps) - 1:
                input("\n[Press Enter for next step...]\n")
        
        print("\n" + "=" * 60)
        print("✅ Walk-through complete!")
        print("=" * 60)
    
    def _present_step(self, step_data: Dict):
        """Present a single walk step with full code and explanation."""
        print(f"\n## Step {step_data['step_number']}: {step_data['title']}")
        print(f"📁 {step_data['file_path']}")
        print()
        
        # Get the actual code
        if "function_or_section" in step_data:
            func_name = step_data["function_or_section"]
            
            # Try to get the function
            result = self.tools.get_function(step_data["file_path"], func_name)
            if not result.success:
                # Fall back to get_class
                result = self.tools.get_class(step_data["file_path"], func_name)
            if not result.success:
                # Fall back to reading file
                result = self.tools.read_file(step_data["file_path"])
            
            code = result.output if result.success else "(Could not retrieve code)"
        else:
            result = self.tools.read_file(step_data["file_path"])
            code = result.output if result.success else "(Could not retrieve code)"
        
        # Display code
        print("```")
        print(code[:3000])  # Limit display
        if len(code) > 3000:
            print("... (truncated)")
        print("```")
        
        # Get data structures if specified
        if step_data.get("data_structures"):
            print("\n### 📦 Key Data Structures\n")
            for ds_name in step_data["data_structures"]:
                ds_result = self.tools.find_definition(ds_name)
                if ds_result.success and ds_result.output != f"No definition found for: {ds_name}":
                    print(f"**{ds_name}:**")
                    print("```")
                    print(ds_result.output[:1000])
                    print("```\n")
        
        # Generate explanation
        explanation = self._generate_step_explanation(step_data, code)
        print("\n### 💡 Explanation\n")
        print(explanation)
        
        # Show what's next
        if step_data.get("leads_to"):
            print(f"\n➡️ **Next:** {step_data['leads_to']}")
    
    def _generate_step_explanation(self, step_data: Dict, code: str) -> str:
        """Generate detailed explanation for a step."""
        
        prompt = f"""Explain this code step in a walk-through about "{self.state.user_request}".

## Step Context
- Title: {step_data['title']}
- Why important: {step_data.get('why_important', 'Part of main flow')}
- Key concepts: {step_data.get('key_concepts', [])}

## Code
```
{code[:4000]}
```

## Instructions

Provide a clear, detailed explanation that:
1. States what this code does at a high level (1-2 sentences)
2. Walks through the key operations line by line
3. Explains any non-obvious logic or algorithms
4. Clarifies how data flows through this code
5. Notes any important patterns or idioms used

Be thorough but readable. Use bullet points sparingly. 
Focus on building understanding, not just describing."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text
```

---

### 5. CLI Interface

```python
#!/usr/bin/env python3
"""
Code Walker CLI - Walk through codebases with AI guidance.

Usage:
    codewalk <repo_path> "<what you want to learn>"
    
Example:
    codewalk ./pytorch "how tensor creation works from Python to C++"
    codewalk ./redis "the complete write path from command to disk"
"""

import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description="Walk through codebases with AI guidance"
    )
    parser.add_argument("repo_path", help="Path to the repository")
    parser.add_argument("request", help="What you want to learn about the codebase")
    parser.add_argument("--model", default="claude-sonnet-4-20250514", 
                        help="Model to use")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed tool outputs")
    
    args = parser.parse_args()
    
    try:
        agent = CodeWalkerAgent(args.repo_path, model=args.model)
        agent.run(args.request)
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

---

### 6. Example Session

```
$ codewalk ./leveldb "how a Put operation writes data to disk"

🎯 Goal: how a Put operation writes data to disk

============================================================

📂 EXPLORATION PHASE

--- Thinking (iteration 1) ---
Action: tree - Get overview of project structure
  🔧 tree({'path': '.', 'max_depth': 2})
  ✓ .
      ├── db
      │   ├── builder.cc
      │   ├── db_impl.cc
      │   ├── db_impl.h
      ...

--- Thinking (iteration 2) ---
Action: read_file - Read README for project overview
  🔧 read_file({'path': 'README.md'})
  ✓    1 | # LevelDB
       2 | 
       3 | LevelDB is a fast key-value storage library...

--- Thinking (iteration 3) ---
Action: grep - Find Put implementation
  🔧 grep({'pattern': 'Status.*Put', 'file_pattern': '*.cc'})
  ✓ db/db_impl.cc:123:Status DBImpl::Put(const WriteOptions& o...

--- Thinking (iteration 4) ---
Action: get_function - Get full Put implementation
  🔧 get_function({'file_path': 'db/db_impl.cc', 'function_name': 'Put'})
  ✓  123 | Status DBImpl::Put(const WriteOptions& o, const Slice& key...

--- Thinking (iteration 5) ---
Action: grep - Find Write function that Put calls
  🔧 grep({'pattern': 'DBImpl::Write', 'file_pattern': '*.cc'})
  ...

--- Thinking (iteration 8) ---
Action: find_definition - Find WriteBatch structure
  🔧 find_definition({'symbol': 'WriteBatch'})
  ...

✅ Exploration complete. Ready to plan.

📋 PLANNING PHASE

📖 LevelDB Put Operation: From API to Disk
   This walk-through traces how a Put() call flows through LevelDB's 
   write path, from the public API through the write-ahead log and 
   finally to the memtable and SST files.
   (7 steps)

============================================================
🚶 CODE WALK-THROUGH
============================================================

# LevelDB Put Operation: From API to Disk

This walk-through traces how a Put() call flows through LevelDB's 
write path, from the public API through the write-ahead log and 
finally to the memtable and SST files.

------------------------------------------------------------

## Step 1: Entry Point: DBImpl::Put()
📁 db/db_impl.cc

```
 123 | Status DBImpl::Put(const WriteOptions& options,
 124 |                    const Slice& key,
 125 |                    const Slice& value) {
 126 |   WriteBatch batch;
 127 |   batch.Put(key, value);
 128 |   return Write(options, &batch);
 129 | }
```

### 📦 Key Data Structures

**WriteBatch:**
```
include/leveldb/write_batch.h:
  class WriteBatch {
    public:
      void Put(const Slice& key, const Slice& value);
      void Delete(const Slice& key);
    private:
      std::string rep_;  // Serialized batch contents
  };
```

### 💡 Explanation

This is the public entry point for writing a key-value pair to LevelDB. 
The implementation is elegantly simple: it wraps the single Put operation 
into a WriteBatch and delegates to the Write() method.

The WriteBatch abstraction serves two purposes:
1. It allows atomic multi-key updates (batch writes)
2. It provides a uniform internal interface - all writes go through 
   the same code path regardless of whether they're single or batch

The Slice type is LevelDB's lightweight string reference - it's just 
a pointer and length, avoiding copies for read-only access.

➡️ **Next:** The Write() method handles batching, WAL, and memtable insertion

[Press Enter for next step...]

## Step 2: Write Batching: DBImpl::Write()
📁 db/db_impl.cc

```
 142 | Status DBImpl::Write(const WriteOptions& options, WriteBatch* updates) {
 143 |   Writer w(&mutex_);
 144 |   w.batch = updates;
 145 |   w.sync = options.sync;
 146 |   w.done = false;
 147 |   
 148 |   MutexLock l(&mutex_);
 149 |   writers_.push_back(&w);
 150 |   while (!w.done && &w != writers_.front()) {
 151 |     w.cv.Wait();
 152 |   }
 153 |   if (w.done) {
 154 |     return w.status;
 155 |   }
 156 |   
 157 |   // Leader writer builds combined batch from queue
 158 |   Status status = MakeRoomForWrite(updates == nullptr);
 159 |   uint64_t last_sequence = versions_->LastSequence();
 160 |   Writer* last_writer = &w;
 ...
```

### 💡 Explanation

This is where LevelDB's write batching magic happens. Instead of each 
write acquiring locks and writing independently, LevelDB uses a 
"leader election" pattern:

1. Each writer joins a queue (writers_.push_back)
2. Writers wait until they reach the front of the queue
3. The front writer becomes the "leader" and processes multiple 
   waiting writes together
4. Other writers whose data was included get notified (w.done = true)

This batching significantly improves throughput under concurrent writes 
because:
- Multiple writes share a single WAL sync operation
- Lock contention is reduced
- The write-ahead log gets larger, more efficient writes

The MakeRoomForWrite() call handles backpressure - if the memtable is 
full, it triggers compaction and may block.

➡️ **Next:** Writing to the write-ahead log for durability

[Press Enter for next step...]

...
```

---

### 7. Tool Summary Table

| Tool | Use When |
|------|----------|
| `tree` | Starting exploration, understanding layout |
| `read_file` | Reading README, configs, specific code |
| `list_dir` | Quick directory contents check |
| `grep` / `git_grep` | Finding patterns, function calls, strings |
| `find_files` | Finding files by name pattern |
| `find_definition` | Finding where something is defined |
| `find_usages` | Finding all references to a symbol |
| `get_function` | Extracting complete function code |
| `get_class` | Extracting complete class/struct |
| `get_imports` | Understanding dependencies |
| `get_outline` | Quick file structure overview |
| `git_log` | Understanding change history |
| `git_blame` | Understanding code authorship |

---

This design gives you a functional agent with about 500 lines of core code. Want me to help implement any specific part, or extend any of the tools?