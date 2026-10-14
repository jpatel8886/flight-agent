import unittest
from datetime import datetime, timezone

from flightagent.__main__ import decide_alert
from flightagent.engine import _combine, merge
from flightagent.models import Itinerary, Segment


def it(price, segs, source="A", strategy="direct"):
    return Itinerary(source=source, strategy=strategy, price=price, currency="USD",
                     segments=[Segment(*s, duration_min=60) for s in segs])


class EngineTest(unittest.TestCase):
    def test_merge_keeps_cheapest_and_records_other_sources(self):
        a = it(500, [("SEA", "DXB", "2026-12-15T10:00", "2026-12-16T11:00")], "A")
        b = it(450, [("SEA", "DXB", "2026-12-15T10:00", "2026-12-16T11:00")], "B")
        out = merge([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, "B")
        self.assertEqual(out[0].also_seen, {"A": 500})

    def test_combine_sums_price_and_total_time(self):
        a = it(400, [("SEA", "DXB", "2026-12-15T10:00", "2026-12-15T11:00")])
        b = it(100, [("DXB", "BOM", "2026-12-15T15:00", "2026-12-15T16:00")])
        c = _combine(a, b, "DXB", 240)
        self.assertEqual(c.price, 500)
        self.assertTrue(c.separate_tickets)
        self.assertEqual(c.total_minutes, 60 + 240 + 60)
        self.assertEqual(c.layovers, ["DXB"])


class AlertTest(unittest.TestCase):
    now = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)

    def test_new_low_requires_min_drop(self):
        st = {"best_price": 1000, "last_digest": "2026-10-14"}
        self.assertIsNone(decide_alert({}, 995, st, {"min_drop": 10}, self.now))
        self.assertIn("new low", decide_alert({}, 980, st, {"min_drop": 10}, self.now))

    def test_digest_once_per_day(self):
        st = {"best_price": 1000}
        alerts = {"daily_digest_utc_hour": 14}
        self.assertEqual(decide_alert({}, 1000, st, alerts, self.now), "daily summary")
        self.assertIsNone(decide_alert({}, 1000, st, alerts, self.now))


if __name__ == "__main__":
    unittest.main()
