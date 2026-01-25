"""Stage 0: repository orientation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .filters import iter_visible_entries, should_skip_path
from .schema import (
    DocumentationFile,
    DocumentationMap,
    DirectoryCategory,
    DirectoryGuide,
    KeyFile,
    ReadingStep,
    RepoOrientation,
)


def _parse_directory_category(raw) -> DirectoryCategory:
    if isinstance(raw, DirectoryCategory):
        return raw
    text = str(raw or "").strip()
    if not text:
        return DirectoryCategory.SUPPORTING
    normalized = text.lower()
    for category in DirectoryCategory:
        if normalized == category.value:
            return category
    for category in DirectoryCategory:
        if normalized == category.name.lower():
            return category
    return DirectoryCategory.SUPPORTING


COLLAPSE_PATTERNS: List[Tuple[str, str]] = [
    (r"tests?/fixtures?/.+", "tests/fixtures/... (N files)"),
    (r"generated/.+", "generated/... (N files)"),
    (r"locale/.+", "locale/... (N files)"),
]


@dataclass
class OrientationContext:
    repo_path: Path
    repo_tree: str
    documentation: DocumentationMap
    root_readme_content: str
    module_readme_summary: str
    design_docs_summary: str
    other_docs_list: str


def generate_repo_tree(repo_path: Path, max_depth: int = 6, use_unicode: bool = True) -> str:
    """Generate a filtered tree view of the repository."""
    repo_path = Path(repo_path).resolve()
    branch_mid = "\u251c\u2500\u2500 " if use_unicode else "|-- "
    branch_last = "\u2514\u2500\u2500 " if use_unicode else "`-- "
    pipe = "\u2502   " if use_unicode else "|   "
    space = "    "

    lines: List[str] = []

    def walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            lines.append(f"{prefix}... (deeper)")
            return

        entries = iter_visible_entries(path, repo_path)
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = branch_last if is_last else branch_mid

            if entry.is_dir():
                collapsed = _collapse_label(entry, repo_path)
                if collapsed:
                    count = _count_files(entry, repo_path)
                    display = _format_collapse_label(collapsed, entry, repo_path)
                    display = display.replace("N", str(count))
                    lines.append(f"{prefix}{connector}{display}")
                    continue

                annotation = _dir_annotation(entry, repo_path)
                lines.append(f"{prefix}{connector}{entry.name}/{annotation}")
                extension = space if is_last else pipe
                walk(entry, prefix + extension, depth + 1)
            else:
                annotation = get_file_annotation(entry)
                lines.append(f"{prefix}{connector}{entry.name}{annotation}")

    lines.append(f"{repo_path.name}/")
    walk(repo_path, "", 1)
    return "\n".join(lines)


def get_file_annotation(path: Path) -> str:
    """Add helpful annotations to important files."""
    name = path.name.lower()

    annotations = {
        "readme.md": "  <- START HERE",
        "readme.rst": "  <- START HERE",
        "readme": "  <- START HERE",
        "contributing.md": "  <- contribution guide",
        "architecture.md": "  <- architecture docs",
        "design.md": "  <- design docs",
        "changelog.md": "  <- version history",
        "license": "  <- license",
        "makefile": "  <- build commands",
        "dockerfile": "  <- container build",
        "docker-compose.yml": "  <- local dev setup",
        ".env.example": "  <- env config template",
    }

    if name in ("package.json", "pyproject.toml", "cargo.toml", "go.mod", "pom.xml"):
        return "  <- project config"

    if name in ("main.py", "main.go", "main.rs", "main.cpp", "index.ts", "index.js", "app.py"):
        return "  <- entry point"

    return annotations.get(name, "")


def discover_all_documentation(repo_path: Path) -> DocumentationMap:
    """Find and categorize all documentation in the repo."""
    repo_path = Path(repo_path).resolve()
    doc_map = DocumentationMap(root_readme=None)

    doc_extensions = {".md", ".rst", ".txt", ".adoc"}

    for path in repo_path.rglob("*"):
        if should_skip_path(path, repo_path):
            continue
        if path.suffix.lower() not in doc_extensions:
            continue
        if not path.is_file():
            continue

        rel_path = path.relative_to(repo_path)
        name_lower = path.name.lower()

        doc_file = DocumentationFile(
            path=str(rel_path),
            kind=_classify_doc(rel_path),
            title=_extract_title(path),
            summary=_extract_summary(path),
            size_lines=_count_lines(path),
        )

        if rel_path.parent == Path(".") and name_lower.startswith("readme"):
            doc_map.root_readme = doc_file
        elif name_lower.startswith("readme"):
            doc_map.module_readmes.append(doc_file)
        elif doc_file.kind == "design":
            doc_map.design_docs.append(doc_file)
        elif doc_file.kind == "api":
            doc_map.api_docs.append(doc_file)
        elif doc_file.kind == "tutorial":
            doc_map.tutorials.append(doc_file)
        elif doc_file.kind == "contributing":
            doc_map.contributing.append(doc_file)
        elif doc_file.kind == "changelog":
            doc_map.changelogs.append(doc_file)
        else:
            doc_map.other_docs.append(doc_file)

    return doc_map


def build_orientation_prompt(
    repo_tree: str,
    root_readme_content: str,
    module_readme_summary: str,
    design_docs_summary: str,
    other_docs_list: str,
) -> str:
    """Build the orientation prompt for the LLM."""
    return ORIENTATION_PROMPT.format(
        repo_tree=repo_tree,
        root_readme_content=root_readme_content,
        module_readmes_summary=module_readme_summary,
        design_docs_summary=design_docs_summary,
        other_docs_list=other_docs_list,
    )


def generate_orientation(
    repo_path: Path,
    llm_client,
    max_depth: int = 6,
    use_unicode: bool = True,
) -> RepoOrientation:
    """Generate a RepoOrientation using the provided LLM client."""
    repo_path = Path(repo_path).resolve()
    repo_tree = generate_repo_tree(repo_path, max_depth=max_depth, use_unicode=use_unicode)
    documentation = discover_all_documentation(repo_path)

    root_readme_content = ""
    if documentation.root_readme:
        root_readme_content = _read_doc_snippet(repo_path / documentation.root_readme.path)

    module_readme_summary = _summarize_doc_list(documentation.module_readmes)
    design_docs_summary = _summarize_doc_list(documentation.design_docs)
    other_docs_list = _list_doc_paths(documentation.other_docs)

    prompt = build_orientation_prompt(
        repo_tree,
        root_readme_content,
        module_readme_summary,
        design_docs_summary,
        other_docs_list,
    )

    context = OrientationContext(
        repo_path=repo_path,
        repo_tree=repo_tree,
        documentation=documentation,
        root_readme_content=root_readme_content,
        module_readme_summary=module_readme_summary,
        design_docs_summary=design_docs_summary,
        other_docs_list=other_docs_list,
    )

    raw = llm_client.generate_orientation(prompt, context)
    data = json.loads(raw)
    return orientation_from_dict(data, repo_tree, documentation)


def orientation_from_dict(
    data: dict,
    structure_tree: str,
    documentation: DocumentationMap,
) -> RepoOrientation:
    """Build RepoOrientation from dict output."""
    directory_guide = [
        DirectoryGuide(
            path=item.get("path", ""),
            category=_parse_directory_category(item.get("category", "supporting")),
            purpose=item.get("purpose", ""),
            key_contents=list(item.get("key_contents", [])),
            read_priority=int(item.get("read_priority", 0)),
        )
        for item in data.get("directory_guide", [])
    ]

    key_files = [
        KeyFile(
            path=item.get("path", ""),
            role=item.get("role", ""),
            description=item.get("description", ""),
        )
        for item in data.get("key_files", [])
    ]

    suggested_reading_order = [
        ReadingStep(
            step=int(item.get("step", 0)),
            what=item.get("what", ""),
            why=item.get("why", ""),
        )
        for item in data.get("suggested_reading_order", [])
    ]

    return RepoOrientation(
        structure_tree=structure_tree,
        documentation=documentation,
        summary=data.get("summary", ""),
        target_audience=data.get("target_audience", ""),
        directory_guide=directory_guide,
        key_files=key_files,
        architecture_overview=data.get("architecture_overview", ""),
        architecture_diagram=data.get("architecture_diagram"),
        data_flow=data.get("data_flow", ""),
        suggested_reading_order=suggested_reading_order,
        gotchas=list(data.get("gotchas", [])),
    )


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _extract_title(path: Path) -> Optional[str]:
    try:
        content = path.read_text(errors="replace")[:2000]
    except OSError:
        return None

    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    match = re.search(r"^(.+)\n[=\-~]+\s*$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    return None


def _extract_summary(path: Path) -> Optional[str]:
    try:
        content = path.read_text(errors="replace")[:5000]
    except OSError:
        return None

    lines = content.split("\n")
    paragraph_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or re.match(r"^[=\-~]+$", stripped):
            if paragraph_lines:
                break
            continue
        if stripped.startswith("![") or stripped.startswith("[!["):
            continue
        if not stripped:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(stripped)
        if len(" ".join(paragraph_lines)) > 300:
            break

    if paragraph_lines:
        summary = " ".join(paragraph_lines)[:300]
        if len(summary) == 300:
            summary = summary.rsplit(" ", 1)[0] + "..."
        return summary
    return None


def _classify_doc(rel_path: Path) -> str:
    name_lower = rel_path.name.lower()
    path_lower = str(rel_path).lower()

    if name_lower.startswith("readme"):
        return "readme"
    if name_lower in ("architecture.md", "design.md") or "design" in path_lower:
        return "design"
    if "api" in path_lower:
        return "api"
    if any(token in path_lower for token in ["tutorial", "guide", "getting-started"]):
        return "tutorial"
    if name_lower.startswith("contrib"):
        return "contributing"
    if name_lower in ("changelog.md", "changes.md", "history.md", "releases.md"):
        return "changelog"
    return "other"


def _read_doc_snippet(path: Path, max_chars: int = 4000) -> str:
    try:
        content = path.read_text(errors="replace")
    except OSError:
        return ""
    return _sanitize_doc_text(content[:max_chars])


def _sanitize_doc_text(text: str) -> str:
    lines = text.splitlines()
    cleaned: List[str] = []
    for line in lines:
        lowered = line.lower()
        if "ignore previous" in lowered or "system prompt" in lowered:
            continue
        if "do not follow" in lowered and "instructions" in lowered:
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _summarize_doc_list(docs: Iterable[DocumentationFile]) -> str:
    parts = []
    for doc in docs:
        title = doc.title or "(untitled)"
        summary = doc.summary or ""
        parts.append(f"- {doc.path}: {title} {summary}".strip())
    return "\n".join(parts)


def _list_doc_paths(docs: Iterable[DocumentationFile]) -> str:
    return "\n".join(f"- {doc.path}" for doc in docs)


def _collapse_label(path: Path, root: Path) -> Optional[str]:
    rel_path = path.relative_to(root).as_posix()
    probe = rel_path + "/placeholder"
    for pattern, replacement in COLLAPSE_PATTERNS:
        if re.match(pattern, probe):
            return replacement
    return None


def _format_collapse_label(label: str, entry: Path, root: Path) -> str:
    parent = entry.parent
    try:
        parent_rel = parent.relative_to(root).as_posix()
    except ValueError:
        return label

    if parent_rel == ".":
        return label
    prefix = parent_rel + "/"
    if label.startswith(prefix):
        return label[len(prefix) :]
    return label


def _count_files(path: Path, root: Path) -> int:
    count = 0
    for child in path.rglob("*"):
        if should_skip_path(child, root):
            continue
        if child.is_file():
            count += 1
    return count


def _dir_annotation(path: Path, root: Path) -> str:
    try:
        count = _count_files(path, root)
    except OSError:
        return ""
    return f"  ({count} files)" if count > 0 else ""


ORIENTATION_PROMPT = """
You are analyzing a codebase to provide an orientation overview for developers.

## Repository Structure

{repo_tree}

## Documentation Found

### Root README
{root_readme_content}

### Module READMEs
{module_readmes_summary}

### Design Documents
{design_docs_summary}

### Other Documentation
{other_docs_list}

## Your Task

Generate an orientation overview that helps a developer understand this codebase.
Your overview should explain:

1. What is this repository?
   - Purpose and main functionality
   - Who is the target user/developer?

2. Directory Structure Explained
   For each major directory, explain:
   - What kind of code/content it contains
   - Its role in the overall system
   - Whether it is essential or supplementary

   Categorize directories as:
   - CORE: Essential logic, must understand
   - IMPORTANT: Significant but can defer
   - SUPPORTING: Config, tests, docs, utilities
   - GENERATED: Can mostly ignore

3. Key Files to Know
   - Entry points (where execution starts)
   - Main configuration files
   - Core abstractions/base classes
   - Public API definitions

4. How the Pieces Fit Together
   - High-level data/control flow
   - Which components depend on which
   - What calls what

5. Suggested Reading Order
   Based on all the above, suggest an order for exploring the codebase.

## Output Format

Provide your overview in this JSON structure:

{{
  "summary": "One paragraph summary of what this repo is and does",
  "target_audience": "Who this repo is for (developers using it, contributors, etc.)",
  "directory_guide": [
    {{
      "path": "src/",
      "category": "core",
      "purpose": "Main package",
      "key_contents": ["module_a", "module_b"],
      "read_priority": 1
    }}
  ],
  "key_files": [
    {{
      "path": "src/__init__.py",
      "role": "public_api",
      "description": "Public API exports"
    }}
  ],
  "architecture_overview": "Brief description...",
  "data_flow": "How data or requests flow...",
  "suggested_reading_order": [
    {{
      "step": 1,
      "what": "README.md",
      "why": "Understand purpose and basic usage"
    }}
  ],
  "gotchas": [
    "Note: generated code lives in generated/"
  ]
}}
""".strip()
