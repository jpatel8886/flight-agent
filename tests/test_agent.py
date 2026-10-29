import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flightagent import agent


class AgentEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/jay").mkdir(parents=True)
        (self.root / "docs/jay/index.html").write_text("<p>old</p>\n<p>keep</p>\n")
        patcher = mock.patch.object(agent, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_allowed_paths(self):
        self.assertTrue(agent.allowed_path("docs/jay/index.html"))
        self.assertTrue(agent.allowed_path("flightagent/engine.py"))
        for bad in [".github/workflows/agent.yml", "docs/data/latest.json", "flightagent/agent.py",
                    "../etc/passwd", "/etc/passwd", "flightagent/../.github/x.py"]:
            self.assertFalse(agent.allowed_path(bad), bad)

    def test_apply_edit(self):
        self.assertEqual(agent.apply_edits([{"path": "docs/jay/index.html", "find": "old", "replace": "new"}]), ["docs/jay/index.html"])
        self.assertEqual((self.root / "docs/jay/index.html").read_text(), "<p>new</p>\n<p>keep</p>\n")

    def test_ambiguous_or_missing_find_changes_nothing(self):
        for find in ["<p>", "absent"]:
            with self.assertRaises(ValueError):
                agent.apply_edits([{"path": "docs/jay/index.html", "find": "old", "replace": "x"},
                                   {"path": "docs/jay/index.html", "find": find, "replace": "y"}])
        self.assertIn("old", (self.root / "docs/jay/index.html").read_text())

    def test_rejects_protected_path(self):
        with self.assertRaises(ValueError):
            agent.apply_edits([{"path": ".github/workflows/monitor.yml", "find": "", "replace": "x"}])


if __name__ == "__main__":
    unittest.main()
