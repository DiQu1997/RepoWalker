import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repowalk.repo_scout.agent import HeuristicLLMClient, RepoScoutAgent
from repowalk.repo_scout.orientation import generate_orientation
from repowalk.repo_scout.preflight import gather_repo_facts
from repowalk.repo_scout.schema import UserGoal
from repowalk.walkthrough.generator import WalkthroughGenerator
from repowalk.walkthrough.navigation import SearchNavigationBackend
from repowalk.walkthrough.steps import StepType


class TestWalkthrough(unittest.TestCase):
    def test_walkthrough_generator_produces_trace_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "README.md").write_text("# Sample\n\nDemo repo")
            (repo / "cli.py").write_text("import argparse\nargparse.ArgumentParser()")
            (repo / "main.py").write_text(
                """
                def main():
                    handle()

                def handle():
                    load_data()

                def load_data():
                    with open('data.txt') as handle:
                        return handle.read()
                """.strip()
            )

            llm = HeuristicLLMClient()
            orientation = generate_orientation(repo, llm, use_unicode=False)
            facts = gather_repo_facts(repo)
            agent = RepoScoutAgent(llm)
            analysis = agent.analyze(repo, facts, orientation)

            self.assertTrue(analysis.surfaces)
            surface = analysis.surfaces[0]

            navigation = SearchNavigationBackend(repo)
            generator = WalkthroughGenerator(
                analysis=analysis,
                navigation=navigation,
                max_depth=4,
                batch_size=3,
            )
            walkthrough = generator.start(UserGoal.DEBUG, surface)

            self.assertTrue(walkthrough.chapters)
            step_types = [step.type for step in walkthrough.chapters[-1].steps]
            self.assertIn(StepType.TRACE, step_types)


if __name__ == "__main__":
    unittest.main()
