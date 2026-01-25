"""Command-line interface for repo scouting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .agent import HeuristicLLMClient, LiteLLMClient, RepoScoutAgent
from .orientation import generate_orientation
from .preflight import gather_repo_facts
from .schema import (
    DirectoryGuide,
    EntryPoint,
    KeyFile,
    RepoAnalysis,
    RepoOrientation,
    Surface,
    UserGoal,
)
from repowalk.walkthrough.generator import WalkthroughGenerator
from repowalk.walkthrough.navigation import SearchNavigationBackend
from repowalk.walkthrough.steps import (
    BranchStep,
    BoundaryStep,
    DataStep,
    OverviewStep,
    RecapStep,
    SurfaceStep,
    TraceStep,
    Walkthrough,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="repowalk")
    subparsers = parser.add_subparsers(dest="command")

    scout = subparsers.add_parser("scout", help="Analyze a repository")
    scout.add_argument("repo", nargs="?", default=".", help="Path to repo")
    scout.add_argument("--max-depth", type=int, default=6, help="Tree depth")
    scout.add_argument(
        "--llm",
        choices=["litellm", "heuristic"],
        default="litellm",
        help="LLM backend",
    )
    scout.add_argument(
        "--model",
        default="gpt-5.2",
        help="LiteLLM model name (when using --llm litellm)",
    )
    scout.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )

    walkthrough = subparsers.add_parser(
        "walkthrough", help="Generate a walkthrough (Phase 2)"
    )
    walkthrough.add_argument("repo", nargs="?", default=".", help="Path to repo")
    walkthrough.add_argument(
        "--goal",
        choices=[goal.value for goal in UserGoal],
        default=UserGoal.DEBUG.value,
        help="Walkthrough goal (default: debug)",
    )
    walkthrough.add_argument(
        "--surface",
        default="0",
        help="Surface index or name (default: 0)",
    )
    walkthrough.add_argument(
        "--list-surfaces",
        action="store_true",
        help="List detected surfaces and exit",
    )
    walkthrough.add_argument("--max-depth", type=int, default=8, help="Trace depth")
    walkthrough.add_argument("--batch-size", type=int, default=5, help="Steps per batch")
    walkthrough.add_argument(
        "--llm",
        choices=["litellm", "heuristic"],
        default="heuristic",
        help="LLM backend (heuristic is offline)",
    )
    walkthrough.add_argument(
        "--model",
        default="gpt-5.2",
        help="LiteLLM model name (when using --llm litellm)",
    )
    walkthrough.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )

    args = parser.parse_args(argv)
    if args.command == "scout":
        repo_path = Path(args.repo).resolve()
        if args.llm == "heuristic":
            llm = HeuristicLLMClient()
        else:
            llm = LiteLLMClient(model=args.model)

        orientation = generate_orientation(repo_path, llm, max_depth=args.max_depth)
        facts = gather_repo_facts(repo_path)
        agent = RepoScoutAgent(llm)
        analysis = agent.analyze(repo_path, facts, orientation)

        if args.output == "json":
            payload = {
                "orientation": orientation_to_dict(orientation),
                "facts": facts_to_dict(facts),
                "analysis": analysis_to_dict(analysis),
            }
            print(json.dumps(payload, indent=2))
        else:
            render_text_output(orientation, facts, analysis)

        return 0

    if args.command == "walkthrough":
        repo_path = Path(args.repo).resolve()
        if args.llm == "heuristic":
            llm = HeuristicLLMClient()
        else:
            llm = LiteLLMClient(model=args.model)

        orientation = generate_orientation(repo_path, llm, max_depth=args.max_depth)
        facts = gather_repo_facts(repo_path)
        agent = RepoScoutAgent(llm)
        analysis = agent.analyze(repo_path, facts, orientation)

        if args.list_surfaces:
            print("SURFACES")
            for idx, surface in enumerate(analysis.surfaces):
                print(f"{idx}: {surface.name} ({surface.kind.value}) @ {surface.location}")
            return 0

        if not analysis.surfaces:
            print("No surfaces detected. Try --llm litellm or inspect repo.")
            return 1

        try:
            surface = select_surface(analysis.surfaces, args.surface)
        except ValueError as exc:
            print(str(exc))
            return 1
        goal = UserGoal(args.goal)

        navigation = SearchNavigationBackend(repo_path)
        generator = WalkthroughGenerator(
            analysis=analysis,
            navigation=navigation,
            max_depth=args.max_depth,
            batch_size=args.batch_size,
        )
        walkthrough = generator.start(goal, surface)
        while walkthrough.has_more:
            generator.continue_walkthrough()

        if args.output == "json":
            payload = walkthrough_to_dict(walkthrough)
            print(json.dumps(payload, indent=2))
        else:
            render_walkthrough_text(walkthrough)

        return 0

    parser.print_help()
    return 1


def render_text_output(
    orientation: RepoOrientation, facts, analysis: RepoAnalysis
) -> None:
    print("STAGE 0: ORIENTATION")
    print(orientation.structure_tree)
    print("\nSUMMARY")
    print(orientation.summary)
    print("\nSTAGE 1: PRE-FLIGHT FACTS")
    print(f"Total files: {facts.total_files}")
    print(f"Build systems: {[bs.kind for bs in facts.build_systems]}")
    print(f"Surface signals: {[s.kind for s in facts.surface_signals]}")
    print("\nSTAGE 2: ANALYSIS")
    print(f"Purpose: {analysis.purpose}")
    print(f"Facets: {analysis.facets}")
    print(f"Surfaces: {[s.name for s in analysis.surfaces]}")


def render_walkthrough_text(walkthrough: Walkthrough) -> None:
    steps = []
    for chapter in walkthrough.chapters:
        steps.extend(chapter.steps)

    print("PHASE 2: WALKTHROUGH")
    print(f"Goal: {walkthrough.goal}")
    print(f"Surface: {walkthrough.surface}")
    if not steps:
        print("No steps generated.")
        return
    print("\nSTEPS")
    for idx, step in enumerate(steps, start=1):
        location = step.location or "-"
        print(f"{idx:02d}. {step.type.value}: {step.title} [{location}]")
        if isinstance(step, BranchStep) and step.options:
            options = ", ".join(
                f"{opt.name} -> {opt.location}" for opt in step.options
            )
            print(f"    options: {options}")


def facts_to_dict(facts) -> Dict[str, Any]:
    return {
        "file_counts_by_extension": facts.file_counts_by_extension,
        "total_files": facts.total_files,
        "total_lines": facts.total_lines,
        "build_systems": [
            {"kind": bs.kind, "config_file": bs.config_file} for bs in facts.build_systems
        ],
        "surface_signals": [
            {
                "kind": s.kind,
                "evidence": s.evidence,
                "locations": s.locations,
            }
            for s in facts.surface_signals
        ],
        "is_monorepo": facts.is_monorepo,
        "workspace_packages": facts.workspace_packages,
        "has_readme": facts.has_readme,
        "readme_path": facts.readme_path,
        "doc_paths": facts.doc_paths,
        "example_paths": facts.example_paths,
        "codegen_markers": [
            {"pattern": m.pattern, "files": m.files} for m in facts.codegen_markers
        ],
        "conventional_entries": facts.conventional_entries,
    }


def orientation_to_dict(orientation: RepoOrientation) -> Dict[str, Any]:
    return {
        "structure_tree": orientation.structure_tree,
        "documentation": documentation_to_dict(orientation.documentation),
        "summary": orientation.summary,
        "target_audience": orientation.target_audience,
        "directory_guide": [directory_guide_to_dict(g) for g in orientation.directory_guide],
        "key_files": [key_file_to_dict(f) for f in orientation.key_files],
        "architecture_overview": orientation.architecture_overview,
        "architecture_diagram": orientation.architecture_diagram,
        "data_flow": orientation.data_flow,
        "suggested_reading_order": [
            {"step": s.step, "what": s.what, "why": s.why}
            for s in orientation.suggested_reading_order
        ],
        "gotchas": orientation.gotchas,
    }


def documentation_to_dict(documentation) -> Dict[str, Any]:
    def doc_to_dict(doc):
        return {
            "path": doc.path,
            "kind": doc.kind,
            "title": doc.title,
            "summary": doc.summary,
            "size_lines": doc.size_lines,
        }

    return {
        "root_readme": doc_to_dict(documentation.root_readme)
        if documentation.root_readme
        else None,
        "module_readmes": [doc_to_dict(d) for d in documentation.module_readmes],
        "design_docs": [doc_to_dict(d) for d in documentation.design_docs],
        "api_docs": [doc_to_dict(d) for d in documentation.api_docs],
        "tutorials": [doc_to_dict(d) for d in documentation.tutorials],
        "contributing": [doc_to_dict(d) for d in documentation.contributing],
        "changelogs": [doc_to_dict(d) for d in documentation.changelogs],
        "other_docs": [doc_to_dict(d) for d in documentation.other_docs],
    }


def directory_guide_to_dict(guide: DirectoryGuide) -> Dict[str, Any]:
    return {
        "path": guide.path,
        "category": guide.category.value,
        "purpose": guide.purpose,
        "key_contents": guide.key_contents,
        "read_priority": guide.read_priority,
    }


def key_file_to_dict(key_file: KeyFile) -> Dict[str, Any]:
    return {
        "path": key_file.path,
        "role": key_file.role,
        "description": key_file.description,
    }


def analysis_to_dict(analysis: RepoAnalysis) -> Dict[str, Any]:
    def surface_to_dict(surface: Surface) -> Dict[str, Any]:
        return {
            "kind": surface.kind.value,
            "name": surface.name,
            "description": surface.description,
            "location": surface.location,
            "importance": surface.importance,
            "commands": surface.commands,
            "routes": surface.routes,
            "exports": surface.exports,
        }

    entry_points = {}
    for goal, entries in analysis.entry_points_by_goal.items():
        entry_points[goal.value] = [entry_point_to_dict(e) for e in entries]

    return {
        "purpose": analysis.purpose,
        "facets": {
            "distribution": analysis.facets.distribution.value,
            "interfaces": analysis.facets.interfaces,
            "structure": analysis.facets.structure.value,
            "runtime": analysis.facets.runtime.value,
            "domain": analysis.facets.domain,
            "codegen": analysis.facets.codegen.value,
        },
        "surfaces": [surface_to_dict(s) for s in analysis.surfaces],
        "entry_points_by_goal": entry_points,
        "key_components": [
            {
                "name": c.name,
                "path": c.path,
                "description": c.description,
                "depends_on": c.depends_on,
                "surfaces": c.surfaces,
            }
            for c in analysis.key_components
        ],
        "examples_and_tests": {
            "examples": analysis.examples_and_tests.examples,
            "integration_tests": analysis.examples_and_tests.integration_tests,
            "golden_path_tests": analysis.examples_and_tests.golden_path_tests,
        },
        "unknowns": analysis.unknowns,
        "confidence": {
            "overall": analysis.confidence.overall,
            "facets": analysis.confidence.facets,
            "surfaces": analysis.confidence.surfaces,
            "components": analysis.confidence.components,
        },
        "reasoning": analysis.reasoning,
        "tool_calls_used": analysis.tool_calls_used,
        "analysis_time_seconds": analysis.analysis_time_seconds,
    }


def walkthrough_to_dict(walkthrough: Walkthrough) -> Dict[str, Any]:
    def step_to_dict(step) -> Dict[str, Any]:
        payload = {
            "type": step.type.value,
            "title": step.title,
            "location": step.location,
            "explanation": step.explanation,
        }
        if isinstance(step, OverviewStep):
            payload["key_concepts"] = step.key_concepts
        if isinstance(step, SurfaceStep):
            payload["surface_kind"] = step.surface_kind
            payload["example_usage"] = step.example_usage
        if isinstance(step, TraceStep):
            payload["calls_to"] = step.calls_to
            payload["called_by"] = step.called_by
        if isinstance(step, DataStep):
            payload["fields"] = step.fields
            payload["used_by"] = step.used_by
        if isinstance(step, BoundaryStep):
            payload["boundary_kind"] = step.boundary_kind
            payload["can_continue"] = step.can_continue
        if isinstance(step, BranchStep):
            payload["options"] = [
                {
                    "name": opt.name,
                    "description": opt.description,
                    "location": opt.location,
                }
                for opt in step.options
            ]
            payload["default_option"] = step.default_option
        if isinstance(step, RecapStep):
            payload["summary"] = step.summary
            payload["mental_model"] = step.mental_model
            payload["next_steps"] = step.next_steps
        return payload

    return {
        "title": walkthrough.title,
        "goal": walkthrough.goal,
        "surface": walkthrough.surface,
        "chapters": [
            {
                "title": chapter.title,
                "description": chapter.description,
                "steps": [step_to_dict(step) for step in chapter.steps],
            }
            for chapter in walkthrough.chapters
        ],
        "has_more": walkthrough.has_more,
        "continuation_context": walkthrough.continuation_context,
    }


def entry_point_to_dict(entry: EntryPoint) -> Dict[str, Any]:
    return {
        "path": entry.path,
        "name": entry.name,
        "description": entry.description,
        "why": entry.why,
    }


def select_surface(surfaces: list[Surface], selector: str) -> Surface:
    if selector.isdigit():
        index = int(selector)
        if index < 0 or index >= len(surfaces):
            raise ValueError("Surface index out of range")
        return surfaces[index]

    needle = selector.strip().lower()
    for surface in surfaces:
        if needle == surface.name.lower():
            return surface
        if needle == surface.kind.value.lower():
            return surface
        if needle == surface.kind.name.lower():
            return surface

    raise ValueError("Surface not found. Use --list-surfaces to see options.")


if __name__ == "__main__":
    raise SystemExit(main())
