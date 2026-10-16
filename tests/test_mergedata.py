import unittest

from flightagent.mergedata import merge_history, merge_lounges


class MergeDataTest(unittest.TestCase):
    def test_history_union_sorted(self):
        theirs = {"a": [{"t": "1", "best": 5}, {"t": "2", "best": 4}]}
        ours = {"a": [{"t": "1", "best": 5}, {"t": "3", "best": 3}], "b": [{"t": "3", "best": 9}]}
        out = merge_history(theirs, ours)
        self.assertEqual([p["t"] for p in out["a"]], ["1", "2", "3"])
        self.assertEqual(out["b"], [{"t": "3", "best": 9}])

    def test_lounges_keep_newest_airport(self):
        theirs = {"index": {"built": "2026-10-01"}, "airports": {"DXB": {"fetched": "2026-10-16"}, "DEL": {"fetched": "2026-10-01"}}}
        ours = {"index": {"built": "2026-10-01"}, "airports": {"DXB": {"fetched": "2026-10-10"}, "DEL": {"fetched": "2026-10-16"}}}
        out = merge_lounges(theirs, ours)
        self.assertEqual(out["airports"]["DXB"]["fetched"], "2026-10-16")
        self.assertEqual(out["airports"]["DEL"]["fetched"], "2026-10-16")


if __name__ == "__main__":
    unittest.main()
