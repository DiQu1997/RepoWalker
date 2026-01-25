import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repowalk.repo_scout.orientation import discover_all_documentation, generate_repo_tree


class TestOrientation(unittest.TestCase):
    def test_generate_repo_tree_filters_and_annotations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "README.md").write_text("# Sample\n\nHello")
            (repo / "src").mkdir()
            (repo / "src" / "main.py").write_text("print('hi')")
            (repo / "node_modules").mkdir()
            (repo / "node_modules" / "ignore.js").write_text("ignore")
            (repo / "tests" / "fixtures").mkdir(parents=True)
            (repo / "tests" / "fixtures" / "data.txt").write_text("data")

            tree = generate_repo_tree(repo, max_depth=4, use_unicode=False)

            self.assertIn(f"{repo.name}/", tree)
            self.assertIn("README.md  <- START HERE", tree)
            self.assertIn("src/", tree)
            self.assertIn("main.py  <- entry point", tree)
            self.assertNotIn("node_modules", tree)
            self.assertNotIn("data.txt", tree)
            self.assertIn("fixtures/... (1 files)", tree)

    def test_discover_all_documentation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "README.md").write_text("# Root Title\n\nRoot summary.")
            (repo / "docs").mkdir()
            (repo / "docs" / "design.md").write_text("# Design Doc\n\nDesign summary.")
            (repo / "docs" / "api.md").write_text("# API\n\nAPI summary.")
            (repo / "docs" / "guide.md").write_text("# Guide\n\nGuide summary.")

            doc_map = discover_all_documentation(repo)

            self.assertIsNotNone(doc_map.root_readme)
            self.assertEqual(doc_map.root_readme.path, "README.md")
            self.assertEqual(doc_map.root_readme.title, "Root Title")
            self.assertTrue(doc_map.design_docs)
            self.assertTrue(doc_map.api_docs)
            self.assertTrue(doc_map.tutorials)

            design_paths = {doc.path for doc in doc_map.design_docs}
            api_paths = {doc.path for doc in doc_map.api_docs}
            guide_paths = {doc.path for doc in doc_map.tutorials}

            self.assertIn("docs/design.md", design_paths)
            self.assertIn("docs/api.md", api_paths)
            self.assertIn("docs/guide.md", guide_paths)


if __name__ == "__main__":
    unittest.main()
