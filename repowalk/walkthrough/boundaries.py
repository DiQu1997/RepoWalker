"""Boundary detection heuristics for walkthrough tracing."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from repowalk.repo_scout.schema import RepoAnalysis
from repowalk.walkthrough.navigation import TraceTarget


@dataclass
class Boundary:
    kind: str
    description: str
    can_cross: bool


def check_boundary(target: TraceTarget, analysis: RepoAnalysis) -> Optional[Boundary]:
    """Check if we've hit a meaningful boundary for the trace."""
    if is_external_dependency(target.location):
        package = get_package_name(target.location)
        return Boundary(
            kind="framework",
            description=f"Entering {package} (external dependency)",
            can_cross=False,
        )

    if is_generated_code(target.location, analysis):
        return Boundary(
            kind="generated",
            description="Generated code - see source-of-truth instead",
            can_cross=False,
        )

    if has_io_operations(target.content or ""):
        return Boundary(
            kind="io",
            description="I/O operation (network/database/filesystem)",
            can_cross=True,
        )

    if is_core_abstraction(target, analysis):
        return Boundary(
            kind="abstraction",
            description=f"Core abstraction: {target.name}",
            can_cross=True,
        )

    if is_repetitive_pattern(target):
        return Boundary(
            kind="repetition",
            description="This pattern repeats for other cases",
            can_cross=False,
        )

    return None


def is_external_dependency(location: str) -> bool:
    lowered = location.lower()
    external_markers = [
        "site-packages",
        "node_modules",
        "vendor/",
        "third_party",
        ".cargo/",
        "gopath/pkg/mod",
    ]
    return any(marker in lowered for marker in external_markers)


def get_package_name(location: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", location) if part]
    if not parts:
        return "dependency"
    if "site-packages" in parts:
        idx = parts.index("site-packages")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if "node_modules" in parts:
        idx = parts.index("node_modules")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1]


def has_io_operations(content: str) -> bool:
    patterns = [
        r"\bopen\(",
        r"\brequests\.",
        r"\bhttp",
        r"\bfetch\(",
        r"\bsocket\b",
        r"\bdb\b",
        r"\bsql\b",
        r"\bquery\(",
        r"\bexecute\(",
        r"\bread\(",
        r"\bwrite\(",
    ]
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)


def is_generated_code(location: str, analysis: RepoAnalysis) -> bool:
    lowered = location.lower()
    if any(marker in lowered for marker in ("generated", "gen", "dist", "build")):
        return True
    for marker in analysis.facts.codegen_markers:
        if any(location.endswith(path) or location == path for path in marker.files):
            return True
    return False


def is_core_abstraction(target: TraceTarget, analysis: RepoAnalysis) -> bool:
    name = target.name.lower()
    for component in analysis.key_components:
        if component.name.lower() == name:
            return True
        if target.location.startswith(component.path):
            return True
    return False


def is_repetitive_pattern(target: TraceTarget) -> bool:
    lowered = target.location.lower()
    if "/tests/" in lowered or lowered.startswith("tests/"):
        return True
    if target.name.lower().endswith("handler"):
        return True
    return False
