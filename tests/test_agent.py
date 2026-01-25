import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repowalk.repo_scout.agent import HeuristicLLMClient, RepoScoutAgent
from repowalk.repo_scout.orientation import generate_orientation
from repowalk.repo_scout.preflight import gather_repo_facts


class TestAgent(unittest.TestCase):
    def test_agent_analysis_parses_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "README.md").write_text("# Sample Repo\n\nSample summary.")
            (repo / "cli.py").write_text("import argparse\nargparse.ArgumentParser()")
            (repo / "main.py").write_text("print('hello')")

            llm = HeuristicLLMClient()
            orientation = generate_orientation(repo, llm, use_unicode=False)
            facts = gather_repo_facts(repo)
            agent = RepoScoutAgent(llm)
            analysis = agent.analyze(repo, facts, orientation)

            self.assertTrue(analysis.purpose)
            self.assertTrue(analysis.facets.interfaces)
            self.assertTrue(analysis.surfaces)
            self.assertGreaterEqual(analysis.tool_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
