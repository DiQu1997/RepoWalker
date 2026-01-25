import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repowalk.repo_scout.preflight import gather_repo_facts


class TestPreflight(unittest.TestCase):
    def test_gather_repo_facts_detects_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "pyproject.toml").write_text("[project]\nname='sample'")
            (repo / "cli.py").write_text("import argparse\nargparse.ArgumentParser()")
            (repo / "api").mkdir()
            (repo / "api" / "routes.py").write_text("router.get('/health')")
            (repo / "packages" / "pkg1").mkdir(parents=True)
            (repo / "packages" / "pkg1" / "package.json").write_text("{}")
            (repo / "packages" / "pkg2").mkdir(parents=True)
            (repo / "packages" / "pkg2" / "package.json").write_text("{}")
            (repo / "generated").mkdir()
            (repo / "generated" / "file.py").write_text("# DO NOT EDIT\n")
            (repo / "main.py").write_text("print('hello')")

            facts = gather_repo_facts(repo)

            build_kinds = {bs.kind for bs in facts.build_systems}
            self.assertIn("pip", build_kinds)

            surface_kinds = {signal.kind for signal in facts.surface_signals}
            self.assertIn("cli", surface_kinds)
            self.assertIn("http", surface_kinds)

            self.assertTrue(facts.is_monorepo)
            self.assertIn("packages/pkg1", facts.workspace_packages)
            self.assertIn("packages/pkg2", facts.workspace_packages)

            self.assertTrue(facts.codegen_markers)
            self.assertIn("main.py", facts.conventional_entries)


if __name__ == "__main__":
    unittest.main()
