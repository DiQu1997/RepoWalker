"""Common path filtering utilities for repo scanning."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


ALWAYS_SKIP = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
    ".egg-info",
    "coverage",
    ".next",
    ".nuxt",
    ".cache",
    "vendor",
    ".tox",
}


TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".cs",
    ".swift",
    ".m",
    ".mm",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".xml",
    ".md",
    ".rst",
    ".txt",
    ".adoc",
}


def should_skip_path(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts

    for part in rel_parts:
        if not part:
            continue
        if part in ALWAYS_SKIP:
            return True
        if part.startswith("."):
            return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    return False


def iter_visible_entries(path: Path, root: Path) -> Iterable[Path]:
    try:
        entries = list(path.iterdir())
    except OSError:
        return []
    visible = [e for e in entries if not should_skip_path(e, root)]
    return sorted(visible, key=lambda x: (x.is_file(), x.name.lower()))
