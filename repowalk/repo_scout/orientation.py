from __future__ import annotations

from typing import Dict, List


def build_exploration_prompt(
    user_request: str,
    repo_path: str,
    exploration_context: str,
    tool_descriptions: List[str],
    repeat_warning: str | None = None,
) -> str:
    tools_text = "\n".join(tool_descriptions)
    warning_text = ""
    if repeat_warning:
        warning_text = f"\n## Repeat Guard\n{repeat_warning}\n"
    return f"""You are exploring a codebase to understand: "{user_request}"

## What You've Learned So Far

Repository: {repo_path}

{exploration_context}

{warning_text}
## Available Tools

{tools_text}

## Your Task

Decide what to do next to understand "{user_request}".

Think step by step:
1. What do I still need to understand?
2. What's the most valuable information to get next?
3. Which tool will give me that information?

Avoid repeating the same tool call with identical arguments. If you already used a tool
and got its output, either pick a different tool or declare you're ready to plan.

If you have enough information to create a walk-through plan (you know the entry point,
the key code path, and relevant data structures), respond with:
{{"type": "done", "reason": "why you're ready"}}

Otherwise, respond with the next tool to use:
{{"type": "tool", "tool": "tool_name", "args": {{"arg1": "value1"}}, "reason": "why this tool"}}

Respond with ONLY the JSON, no other text."""


def build_plan_prompt(
    user_request: str,
    exploration_context: str,
    full_tool_results: str,
) -> str:
    return f"""Based on your exploration, create a detailed walk-through plan for:
"{user_request}"

## Exploration Results

{exploration_context}

## Full Tool Results

{full_tool_results}

## Instructions

Create a step-by-step walk-through plan. For each step:
1. Identify the exact file and line range (use start_line/end_line if you can)
2. Explain what that code does
3. Identify any data structures that need explanation
4. Explain how it connects to the next step

Important: file_path must be a specific file (include extension). Do not return
directories like "src" or "core"; pick the exact source file that contains the code.

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
            "start_line": 1,
            "end_line": 10,
            "why_important": "Why this step matters",
            "data_structures": ["TypeA", "TypeB"],
            "key_concepts": ["concept1", "concept2"],
            "leads_to": "What this step leads to next"
        }}
    ]
}}

Include 5-10 steps covering the complete code path. Be specific about files and functions."""


def build_step_explanation_prompt(
    user_request: str,
    step_data: Dict,
    code: str,
) -> str:
    return f"""Explain this code step in a walk-through about "{user_request}".

## Step Context
- Title: {step_data.get("title", "")}
- Why important: {step_data.get("why_important", "Part of main flow")}
- Key concepts: {step_data.get("key_concepts", [])}

## Code
```
{code}
```

## Instructions

Provide a clear, detailed and focused explanation of this code block, emphasizing key logic and data structures.
- **Focus on substance**: Explain the core business logic, algorithms, and data transformations. Avoid redundant descriptions of simple syntax or standard boilerplate.
- **Highlight complexity**: Specifically address edge cases, error handling, or non-obvious implementation details that matter.
- **Structure**: Use cohesive paragraphs for the narrative. **Only use bullet points when strictly necessary** (e.g., listing distinct conditions or side effects).
- **Depth**: Provide enough detail to understand *how* and *why* the code works, but skip trivial "single-line small stuff" unless it impacts the broader flow.

Your goal is to clarify the mechanism and intent of this step without over-explaining the obvious.
Focus on building understanding, not just describing."""


def build_step_flow_prompt(
    user_request: str,
    step_data: Dict,
    code: str,
) -> str:
    return f"""Create a concise ASCII flow diagram for this code step about "{user_request}".

## Step Context
- Title: {step_data.get("title", "")}
- Why important: {step_data.get("why_important", "Part of main flow")}
- Key concepts: {step_data.get("key_concepts", [])}

## Code
```
{code}
```

## Instructions

Produce ONLY an ASCII flow diagram. No prose, no bullets, no markdown fences.

Diagram conventions:
- Use plain text nodes (no bracketed tags like `[Start]`, `[End]`, `[return]`, `[error]`, `[action]`).
- Use arrows to show order: `->` for forward flow.
- Decision: use a node like `if <condition>` with branch lines prefixed `->` (no yes/no labels).
- Loop: show a back-edge with `↺` or `<-` and a short loop condition.
- Switch: use a node like `switch <expr>` with branch lines `-> <case>` (no `case`/`default` labels unless needed for clarity).

Abstraction rules (important):
- Aim for 3–7 main nodes max (excluding Start/End).
- Group trivial steps (assignments, cache lookups, minor transforms) into one node.
- Prefer intent labels: e.g., `[load config]`, `[validate input]`, `[resolve path]`.
- Only show branches that change control flow or outcomes.
- If there are many checks, group them based on their purpose like validate output format, validate user auth or so.

Quality rules:
- Show the *actual* control flow (major branches, early exits, error paths).
- Keep width under 90 characters.
- If flow is linear, show a simple chain.
- If flow is unclear, produce a high-level best-effort flow rather than guessing details."""


def build_overview_flow_prompt(
    user_request: str,
    plan_overview: str,
    steps: List[Dict],
) -> str:
    steps_text = "\n".join(
        [
            f"{s.get('step_number')}. {s.get('title')} | {s.get('file_path')} | "
            f"{s.get('function_or_section') or ''} | leads_to={s.get('leads_to') or ''}"
            for s in steps
        ]
    )
    return f"""Create a high-level overview of the entire code flow for:
"{user_request}"

## Plan Overview
{plan_overview}

## Steps (ordered)
{steps_text}

## Instructions

Return ONLY JSON with this shape:
{{
  "flow": "ASCII flow diagram",
  "summary": "2-4 sentence high-level explanation of the whole flow",
  "data_flow": ["key data structure -> transformation", "…"]
}}

Flow guidelines:
- Use plain text nodes (no bracketed tags).
- Prefer labels like `step 1: ... (file)` for major calls/sections.
- Show cross-file transitions and major call flow.
- Use `if <condition>` for branching when steps imply it (no yes/no labels).
- Keep width under 90 characters.
- Prefer clarity over completeness; stick to provided steps."""
