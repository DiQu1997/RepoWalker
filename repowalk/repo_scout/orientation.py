from __future__ import annotations

from typing import Dict, List


def build_exploration_prompt(
    user_request: str,
    repo_path: str,
    exploration_context: str,
    tool_descriptions: List[str],
) -> str:
    tools_text = "\n".join(tool_descriptions)
    return f"""You are exploring a codebase to understand: "{user_request}"

## What You've Learned So Far

Repository: {repo_path}

{exploration_context}

## Available Tools

{tools_text}

## Your Task

Decide what to do next to understand "{user_request}".

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
