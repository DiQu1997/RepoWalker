"""Step types and walkthrough schema for phase 2."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union


class StepType(Enum):
    OVERVIEW = "overview"
    SURFACE = "surface"
    TRACE = "trace"
    DATA = "data"
    BOUNDARY = "boundary"
    BRANCH = "branch"
    RECAP = "recap"


@dataclass
class BaseStep:
    """Base class for all step types."""

    title: str
    location: str
    explanation: str
    type: StepType = field(init=False)


@dataclass
class OverviewStep(BaseStep):
    """Overview of a component or surface."""

    type: StepType = field(init=False, default=StepType.OVERVIEW)
    key_concepts: List[str] = field(default_factory=list)


@dataclass
class SurfaceStep(BaseStep):
    """Entry point of a surface (API, CLI command, route, etc.)."""

    type: StepType = field(init=False, default=StepType.SURFACE)
    surface_kind: Optional[str] = None
    example_usage: Optional[str] = None


@dataclass
class TraceStep(BaseStep):
    """Follow execution through a function or method."""

    type: StepType = field(init=False, default=StepType.TRACE)
    calls_to: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)


@dataclass
class DataStep(BaseStep):
    """Key data structure or type."""

    type: StepType = field(init=False, default=StepType.DATA)
    fields: List[str] = field(default_factory=list)
    used_by: List[str] = field(default_factory=list)


@dataclass
class BoundaryStep(BaseStep):
    """Reached a boundary in the trace."""

    type: StepType = field(init=False, default=StepType.BOUNDARY)
    boundary_kind: Optional[str] = None
    can_continue: bool = False


@dataclass
class BranchOption:
    """Branch option presented to the user."""

    name: str
    description: str
    location: str


@dataclass
class BranchStep(BaseStep):
    """Multiple paths available - user chooses."""

    type: StepType = field(init=False, default=StepType.BRANCH)
    options: List[BranchOption] = field(default_factory=list)
    default_option: int = 0


@dataclass
class RecapStep(BaseStep):
    """Summary of what was learned."""

    type: StepType = field(init=False, default=StepType.RECAP)
    summary: Optional[str] = None
    mental_model: Optional[str] = None
    next_steps: List[str] = field(default_factory=list)


Step = Union[OverviewStep, SurfaceStep, TraceStep, DataStep, BoundaryStep, BranchStep, RecapStep]


@dataclass
class Chapter:
    """A logical grouping of steps."""

    title: str
    description: str
    steps: List[Step] = field(default_factory=list)


@dataclass
class Walkthrough:
    """Complete walkthrough of a codebase path."""

    title: str
    goal: str
    surface: str
    chapters: List[Chapter] = field(default_factory=list)

    has_more: bool = False
    continuation_context: Optional[dict] = None

    def add_step(
        self,
        step: Step,
        chapter_title: str = "Walkthrough",
        chapter_description: str = "Generated walkthrough steps.",
    ) -> None:
        if not self.chapters:
            self.chapters.append(
                Chapter(title=chapter_title, description=chapter_description, steps=[])
            )
        self.chapters[-1].steps.append(step)
