"""Walkthrough generation for phase 2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from repowalk.repo_scout.schema import EntryPoint, RepoAnalysis, Surface, UserGoal
from repowalk.walkthrough.boundaries import Boundary, check_boundary
from repowalk.walkthrough.navigation import BranchPoint, NavigationBackend, TraceContext, TraceTarget
from repowalk.walkthrough.steps import (
    BaseStep,
    BranchOption,
    BranchStep,
    BoundaryStep,
    DataStep,
    OverviewStep,
    RecapStep,
    SurfaceStep,
    TraceStep,
    Walkthrough,
)


@dataclass
class Scenario:
    name: str
    location: str
    description: str
    surface_kind: Optional[str] = None
    example_usage: Optional[str] = None


def generate_walkthrough(
    analysis: RepoAnalysis,
    user_goal: UserGoal,
    selected_surface: Surface,
    navigation: NavigationBackend,
    max_depth: int = 10,
) -> Walkthrough:
    """Generate a walkthrough eagerly until completion or depth limit."""
    generator = WalkthroughGenerator(
        analysis=analysis,
        navigation=navigation,
        max_depth=max_depth,
    )
    walkthrough = generator.start(user_goal, selected_surface)
    while walkthrough.has_more:
        generator.continue_walkthrough()
    return walkthrough


class WalkthroughGenerator:
    """Generates walkthrough steps lazily."""

    def __init__(
        self,
        analysis: RepoAnalysis,
        navigation: NavigationBackend,
        max_depth: int = 10,
        batch_size: int = 5,
    ) -> None:
        self.analysis = analysis
        self.navigation = navigation
        self.max_depth = max_depth
        self.batch_size = batch_size
        self.current_walkthrough: Optional[Walkthrough] = None
        self.trace_context: Optional[TraceContext] = None
        self._current_surface: Optional[Surface] = None
        self._current_goal: Optional[UserGoal] = None

    def start(self, goal: UserGoal, surface: Surface) -> Walkthrough:
        """Start a new walkthrough and return the first batch of steps."""
        self._current_goal = goal
        self._current_surface = surface
        walkthrough = Walkthrough(
            title=f"{self.analysis.purpose} - {surface.name}",
            goal=goal.value if isinstance(goal, UserGoal) else str(goal),
            surface=surface.name,
            chapters=[],
        )

        scenario = pick_scenario(self.analysis, surface, goal)
        self.trace_context = TraceContext(
            current_location=scenario.location,
            depth=0,
            max_depth=self.max_depth,
            visited=set(),
            branch_points=[],
        )

        overview = OverviewStep(
            title=f"Overview: {surface.name}",
            location=surface.location or scenario.location,
            explanation=generate_surface_overview(self.analysis, surface),
            key_concepts=_surface_key_concepts(surface),
        )
        walkthrough.add_step(overview)

        surface_step = SurfaceStep(
            title=f"Entry: {scenario.name}",
            location=scenario.location,
            explanation=generate_scenario_intro(scenario),
            surface_kind=scenario.surface_kind,
            example_usage=scenario.example_usage,
        )
        walkthrough.add_step(surface_step)

        steps, finished = self._trace_steps(self.batch_size)
        self._append_steps(walkthrough, steps)
        self._finalize_walkthrough(walkthrough, finished)

        self.current_walkthrough = walkthrough
        return walkthrough

    def continue_walkthrough(self) -> List[BaseStep]:
        """Generate the next batch of steps for the current path."""
        if not self.current_walkthrough or not self.trace_context:
            return []

        steps, finished = self._trace_steps(self.batch_size)
        self._append_steps(self.current_walkthrough, steps)
        self._finalize_walkthrough(self.current_walkthrough, finished)
        return steps

    def take_branch(self, branch_index: int) -> List[BaseStep]:
        """User chose a branch. Generate steps for that path."""
        if not self.trace_context:
            return []
        if not self.trace_context.branch_points:
            return []

        branch_point = self.trace_context.branch_points[-1]
        if branch_index < 0 or branch_index >= len(branch_point.options):
            raise ValueError("Branch index out of range")

        target = branch_point.options[branch_index]
        self.trace_context.current_location = target.location
        steps, finished = self._trace_steps(self.batch_size)
        if self.current_walkthrough:
            self._append_steps(self.current_walkthrough, steps)
            self._finalize_walkthrough(self.current_walkthrough, finished)
        return steps

    def dive_deeper(self, step_index: int) -> List[BaseStep]:
        """Explore a step in more detail by tracing from its location."""
        if not self.current_walkthrough:
            return []
        if not self.current_walkthrough.chapters:
            return []

        steps = self.current_walkthrough.chapters[-1].steps
        if step_index < 0 or step_index >= len(steps):
            raise ValueError("Step index out of range")

        location = steps[step_index].location
        self.trace_context = TraceContext(
            current_location=location,
            depth=0,
            max_depth=self.max_depth,
            visited=set(),
            branch_points=[],
        )
        next_steps, finished = self._trace_steps(self.batch_size)
        if self.current_walkthrough:
            self._append_steps(self.current_walkthrough, next_steps)
            self._finalize_walkthrough(self.current_walkthrough, finished)
        return next_steps

    def _trace_steps(self, batch_size: int) -> Tuple[List[BaseStep], bool]:
        steps: List[BaseStep] = []
        finished = False

        while len(steps) < batch_size:
            if not self.trace_context:
                finished = True
                break
            if self.trace_context.depth >= self.trace_context.max_depth:
                finished = True
                break

            next_targets = self.navigation.find_next_steps(
                self.trace_context.current_location
            )
            if not next_targets:
                finished = True
                break

            boundary = check_boundary(next_targets[0], self.analysis)
            if boundary:
                steps.append(_boundary_step(boundary, next_targets[0]))
                if not boundary.can_cross:
                    finished = True
                    break

            if len(next_targets) > 1:
                branch_point = BranchPoint(
                    location=self.trace_context.current_location,
                    options=next_targets,
                )
                self.trace_context.branch_points.append(branch_point)
                steps.append(_branch_step(next_targets, self.trace_context.current_location))
                if len(steps) >= batch_size:
                    break

            primary = next_targets[0]
            if primary.location in self.trace_context.visited:
                finished = True
                break

            steps.append(_build_trace_step(primary, self.analysis))
            self.trace_context.current_location = primary.location
            self.trace_context.depth += 1
            self.trace_context.visited.add(primary.location)

        return steps, finished

    def _append_steps(self, walkthrough: Walkthrough, steps: List[BaseStep]) -> None:
        for step in steps:
            walkthrough.add_step(step)

    def _finalize_walkthrough(self, walkthrough: Walkthrough, finished: bool) -> None:
        if finished:
            recap = _recap_step(walkthrough)
            walkthrough.add_step(recap)
            walkthrough.has_more = False
            walkthrough.continuation_context = None
        else:
            walkthrough.has_more = True
            walkthrough.continuation_context = _build_continuation(self.trace_context)


def pick_scenario(
    analysis: RepoAnalysis, surface: Surface, user_goal: UserGoal
) -> Scenario:
    entry = _pick_entry_point(analysis, user_goal)
    if entry:
        return Scenario(
            name=entry.name,
            location=entry.path,
            description=entry.description,
            surface_kind=surface.kind.value,
        )
    return Scenario(
        name=surface.name,
        location=surface.location,
        description=surface.description,
        surface_kind=surface.kind.value,
        example_usage=_surface_example(surface),
    )


def _pick_entry_point(
    analysis: RepoAnalysis, user_goal: UserGoal
) -> Optional[EntryPoint]:
    if isinstance(user_goal, UserGoal):
        entries = analysis.entry_points_by_goal.get(user_goal, [])
    else:
        try:
            goal = UserGoal(str(user_goal))
        except ValueError:
            entries = []
        else:
            entries = analysis.entry_points_by_goal.get(goal, [])
    return entries[0] if entries else None


def generate_surface_overview(analysis: RepoAnalysis, surface: Surface) -> str:
    purpose = analysis.purpose or "Repository overview"
    location = surface.location or "repository"
    return (
        f"{surface.name} is a {surface.kind.value} surface in {purpose}. "
        f"Start at {location} to see how it is wired."
    )


def generate_scenario_intro(scenario: Scenario) -> str:
    return f"Start with {scenario.name}. {scenario.description}".strip()


def _surface_example(surface: Surface) -> Optional[str]:
    if surface.commands:
        return "Example command: " + surface.commands[0]
    if surface.routes:
        return "Example route: " + surface.routes[0]
    if surface.exports:
        return "Example export: " + surface.exports[0]
    return None


def _surface_key_concepts(surface: Surface) -> List[str]:
    concepts = [surface.kind.value]
    if surface.importance:
        concepts.append(surface.importance)
    return concepts


def _boundary_step(boundary: Boundary, target: TraceTarget) -> BoundaryStep:
    return BoundaryStep(
        title=f"Boundary: {boundary.kind}",
        location=target.location,
        explanation=boundary.description,
        boundary_kind=boundary.kind,
        can_continue=boundary.can_cross,
    )


def _branch_step(targets: List[TraceTarget], location: str) -> BranchStep:
    options = [_describe_branch(target) for target in targets]
    return BranchStep(
        title="Choose a path",
        location=location,
        explanation="Multiple paths available. Choose one to explore next.",
        options=options,
        default_option=0,
    )


def _describe_branch(target: TraceTarget) -> BranchOption:
    description = target.preview or f"Trace into {target.name}"
    return BranchOption(
        name=target.name,
        description=description,
        location=target.location,
    )


def _build_trace_step(target: TraceTarget, analysis: RepoAnalysis) -> BaseStep:
    step_type = _classify_step(target, analysis)
    if step_type == "data":
        return DataStep(
            title=f"Data: {target.name}",
            location=target.location,
            explanation=generate_data_explanation(target),
        )
    return TraceStep(
        title=f"Trace: {target.name}",
        location=target.location,
        explanation=generate_trace_explanation(target),
        calls_to=target.calls_to,
        called_by=target.called_by,
    )


def _classify_step(target: TraceTarget, analysis: RepoAnalysis) -> str:
    if target.kind in {"class", "struct", "interface"}:
        return "data"
    lowered = target.location.lower()
    if any(marker in lowered for marker in ("models", "schema", "types")):
        return "data"
    for component in analysis.key_components:
        if component.name.lower() == target.name.lower() and "model" in component.name.lower():
            return "data"
    return "trace"


def generate_trace_explanation(target: TraceTarget) -> str:
    preview = target.preview
    if preview:
        return f"Follow {target.name}. Definition: {preview}"
    return f"Follow {target.name} to see the next call in the flow."


def generate_data_explanation(target: TraceTarget) -> str:
    preview = target.preview
    if preview:
        return f"Key data type {target.name}. Definition: {preview}"
    return f"Key data type {target.name} used across this path."


def _recap_step(walkthrough: Walkthrough) -> RecapStep:
    summary = generate_recap(walkthrough)
    mental_model = generate_mental_model(walkthrough)
    return RecapStep(
        title="What you learned",
        location="",
        explanation="Recap of the walkthrough.",
        summary=summary,
        mental_model=mental_model,
        next_steps=_next_steps_hint(walkthrough),
    )


def generate_recap(walkthrough: Walkthrough) -> str:
    steps = walkthrough.chapters[-1].steps if walkthrough.chapters else []
    trace_titles = [step.title for step in steps if isinstance(step, TraceStep)]
    data_titles = [step.title for step in steps if isinstance(step, DataStep)]
    recap_parts = []
    if trace_titles:
        recap_parts.append("Traced: " + ", ".join(trace_titles[:4]))
    if data_titles:
        recap_parts.append("Data: " + ", ".join(data_titles[:3]))
    if not recap_parts:
        recap_parts.append("Walkthrough complete.")
    return " | ".join(recap_parts)


def generate_mental_model(walkthrough: Walkthrough) -> str:
    steps = walkthrough.chapters[-1].steps if walkthrough.chapters else []
    path = [step.title.replace("Trace: ", "") for step in steps if isinstance(step, TraceStep)]
    if not path:
        return "(no trace steps)"
    return " -> ".join(path[:6])


def _next_steps_hint(walkthrough: Walkthrough) -> List[str]:
    steps = walkthrough.chapters[-1].steps if walkthrough.chapters else []
    hints = []
    for step in steps:
        if isinstance(step, BoundaryStep) and step.can_continue:
            hints.append(f"Dive deeper into {step.boundary_kind} boundary")
    return hints


def _build_continuation(trace_context: Optional[TraceContext]) -> Optional[dict]:
    if not trace_context:
        return None
    return {
        "current_location": trace_context.current_location,
        "depth": trace_context.depth,
        "max_depth": trace_context.max_depth,
        "visited": list(trace_context.visited),
    }
