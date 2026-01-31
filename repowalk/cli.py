from __future__ import annotations

import argparse
import sys

from .repo_scout.agent import CodeWalkerAgent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Walk through codebases with AI guidance"
    )
    parser.add_argument("repo_path", help="Path to the repository")
    parser.add_argument("request", help="What you want to learn about the codebase")
    parser.add_argument("--model", default="gpt-5.2", help="Model to use")
    parser.add_argument(
        "--max-explore-iterations",
        type=int,
        default=25,
        help="Maximum exploration steps before planning",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed tool outputs",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not pause between walk-through steps",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run the terminal UI",
    )
    parser.add_argument(
        "--flow",
        action="store_true",
        help="Generate ASCII flow diagrams for each step",
    )
    parser.add_argument(
        "--llm-log",
        action="store_true",
        help="Write full LLM request/response logs to a JSONL file",
    )
    parser.add_argument(
        "--llm-log-path",
        default=None,
        help="Path for LLM logs (default: ./repowalk_llm_calls.jsonl)",
    )

    args = parser.parse_args(argv)

    try:
        agent = CodeWalkerAgent(
            args.repo_path,
            model=args.model,
            max_explore_iterations=args.max_explore_iterations,
            verbose=args.verbose,
            pause_between_steps=not args.no_pause,
            flow_diagrams=args.flow,
            llm_log=args.llm_log,
            llm_log_path=args.llm_log_path,
        )
        if args.tui:
            from .tui import build_session
            from .ui.terminal import start_terminal_ui

            session = build_session(agent, args.request)
            start_terminal_ui(session, agent, debug=args.verbose)
        else:
            agent.run(args.request)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1
    except Exception as exc:
        print(f"\nError: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
