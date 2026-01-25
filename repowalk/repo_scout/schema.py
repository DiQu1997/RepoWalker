"""Data models for RepoWalk phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Distribution(Enum):
    LIBRARY = "library"
    BINARY = "binary"
    BOTH = "both"


class Structure(Enum):
    SINGLE_PACKAGE = "single-package"
    MONOREPO = "monorepo"
    WORKSPACE = "workspace"


class Runtime(Enum):
    INTERPRETED = "interpreted"
    COMPILED = "compiled"
    MIXED = "mixed"


class Codegen(Enum):
    NONE = "none"
    PARTIAL = "partial"
    HEAVY = "heavy"


class SurfaceKind(Enum):
    CLI = "cli"
    HTTP = "http"
    GRPC = "grpc"
    PUBLIC_API = "public_api"
    PLUGIN = "plugin"
    CONFIG = "config"
    UI = "ui"


class UserGoal(Enum):
    USE = "use"
    CONTRIBUTE = "contribute"
    DEBUG = "debug"
    ARCHITECTURE = "architecture"


class DirectoryCategory(Enum):
    CORE = "core"
    IMPORTANT = "important"
    SUPPORTING = "supporting"
    GENERATED = "generated"


@dataclass
class SurfaceSignal:
    kind: str
    evidence: str
    locations: List[str]


@dataclass
class BuildSystem:
    kind: str
    config_file: str


@dataclass
class CodegenMarker:
    pattern: str
    files: List[str]


@dataclass
class RepoFacts:
    file_counts_by_extension: Dict[str, int]
    total_files: int
    total_lines: int
    build_systems: List[BuildSystem]
    surface_signals: List[SurfaceSignal]
    is_monorepo: bool
    workspace_packages: List[str]
    has_readme: bool
    readme_path: Optional[str]
    doc_paths: List[str]
    example_paths: List[str]
    codegen_markers: List[CodegenMarker]
    conventional_entries: List[str]


@dataclass
class Facets:
    distribution: Distribution
    interfaces: List[str]
    structure: Structure
    runtime: Runtime
    domain: List[str]
    codegen: Codegen


@dataclass
class Surface:
    kind: SurfaceKind
    name: str
    description: str
    location: str
    importance: str
    commands: Optional[List[str]] = None
    routes: Optional[List[str]] = None
    exports: Optional[List[str]] = None


@dataclass
class EntryPoint:
    path: str
    name: str
    description: str
    why: str


@dataclass
class Component:
    name: str
    path: str
    description: str
    depends_on: List[str]
    surfaces: List[str]


@dataclass
class ExamplesAndTests:
    examples: List[str] = field(default_factory=list)
    integration_tests: List[str] = field(default_factory=list)
    golden_path_tests: List[str] = field(default_factory=list)


@dataclass
class ConfidenceScores:
    overall: str
    facets: str
    surfaces: str
    components: str


@dataclass
class DocumentationFile:
    path: str
    kind: str
    title: Optional[str]
    summary: Optional[str]
    size_lines: int


@dataclass
class DocumentationMap:
    root_readme: Optional[DocumentationFile]
    module_readmes: List[DocumentationFile] = field(default_factory=list)
    design_docs: List[DocumentationFile] = field(default_factory=list)
    api_docs: List[DocumentationFile] = field(default_factory=list)
    tutorials: List[DocumentationFile] = field(default_factory=list)
    contributing: List[DocumentationFile] = field(default_factory=list)
    changelogs: List[DocumentationFile] = field(default_factory=list)
    other_docs: List[DocumentationFile] = field(default_factory=list)


@dataclass
class DirectoryGuide:
    path: str
    category: DirectoryCategory
    purpose: str
    key_contents: List[str]
    read_priority: int


@dataclass
class KeyFile:
    path: str
    role: str
    description: str


@dataclass
class ReadingStep:
    step: int
    what: str
    why: str


@dataclass
class RepoOrientation:
    structure_tree: str
    documentation: DocumentationMap
    summary: str
    target_audience: str
    directory_guide: List[DirectoryGuide]
    key_files: List[KeyFile]
    architecture_overview: str
    architecture_diagram: Optional[str]
    data_flow: str
    suggested_reading_order: List[ReadingStep]
    gotchas: List[str]


@dataclass
class RepoAnalysis:
    orientation: RepoOrientation
    facts: RepoFacts
    purpose: str
    facets: Facets
    surfaces: List[Surface]
    entry_points_by_goal: Dict[UserGoal, List[EntryPoint]]
    key_components: List[Component]
    examples_and_tests: ExamplesAndTests
    unknowns: List[str]
    confidence: ConfidenceScores
    reasoning: str
    tool_calls_used: int
    analysis_time_seconds: float
