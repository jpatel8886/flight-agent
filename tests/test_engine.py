import unittest
from datetime import datetime, timezone

from flightagent.__main__ import change_note, email_slot
from flightagent.engine import Ranker, _combine, merge
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


class AvoidCountriesTest(unittest.TestCase):
    def test_flags_layover_in_avoided_country(self):
        from flightagent.__main__ import avoided
        o = {"layovers": ["DEL", "RUH"]}
        self.assertTrue(avoided(o, {"saudi arabia"}))
        self.assertFalse(avoided({"layovers": ["DEL", "LHR"]}, {"saudi arabia"}))


class LayoverFilterTest(unittest.TestCase):
    def test_long_layover_and_excluded_airport_dropped(self):
        from flightagent.engine import Searcher
        s = Searcher({"max_layover_hours": 8, "exclude_airports": ["RUH"]})
        short = it(900, [("AMD", "DEL", "2027-01-09T04:00", "2027-01-09T06:00"),
                         ("DEL", "IAD", "2027-01-09T09:00", "2027-01-09T20:00")])
        long_ = it(800, [("AMD", "DEL", "2027-01-09T04:00", "2027-01-09T06:00"),
                         ("DEL", "IAD", "2027-01-09T15:00", "2027-01-10T02:00")])
        via_ruh = it(700, [("AMD", "RUH", "2027-01-09T04:00", "2027-01-09T06:00"),
                           ("RUH", "IAD", "2027-01-09T08:00", "2027-01-09T20:00")])
        self.assertEqual(s._fits([short, long_, via_ruh]), [short])


class RankerTest(unittest.TestCase):
    def test_shorter_fewer_stops_beats_slightly_cheaper(self):
        r = Ranker({})
        short = it(900, [("AMD", "DXB", "2027-01-08T04:00", "2027-01-08T06:00"),
                         ("DXB", "IAD", "2027-01-08T09:00", "2027-01-08T15:00")])
        long_ = it(820, [("AMD", "DEL", "2027-01-08T04:00", "2027-01-08T06:00"),
                         ("DEL", "RUH", "2027-01-08T20:00", "2027-01-08T22:00"),
                         ("RUH", "IAD", "2027-01-09T12:00", "2027-01-09T18:00")])
        self.assertEqual(r.rank([long_, short])[0], short)


class EmailScheduleTest(unittest.TestCase):
    alerts = {"utc_offset_hours": 5.5, "send_hours_local": [7, 12, 17, 21]}

    def slot(self, h, m=0):
        return email_slot(datetime(2026, 10, 15, h, m, tzinfo=timezone.utc), self.alerts)

    def test_four_windows_per_day(self):
        # 06:30 UTC = 12:00 IST opens the 12:00 window; 11:00 UTC = 16:30 IST is still in it.
        self.assertEqual(self.slot(6, 30), "2026-10-15T12")
        self.assertEqual(self.slot(11, 0), "2026-10-15T12")
        self.assertEqual(self.slot(11, 30), "2026-10-15T17")
        # 00:00 UTC = 05:30 IST: still yesterday's 21:00 window.
        self.assertEqual(self.slot(0, 0), "2026-10-14T21")
        hours = {self.slot(h, m) for h in range(24) for m in (0, 30)}
        self.assertEqual(len(hours), 5)  # 4 windows today + the tail of yesterday's last one

    def test_change_note(self):
        o = {"price": 900, "score": 1300, "total_minutes": 1560, "stops": 1}
        self.assertEqual(change_note(o, o, {}, {}), "first result")
        self.assertIn("better", change_note(o, o, {}, {"emailed_score": 1400}))
        self.assertIn("target", change_note(o, o, {"target_price": 950}, {"emailed_score": 1300}))


class LoungeParseTest(unittest.TestCase):
    def test_payload_and_objects(self):
        import json
        from flightagent import lounges
        data = '{"key":1,"name":"Marhaba","terminalName":"T3","loungeCode":"DXB3","outletCategory":"LOUNGE","ratings":{"average":3.8,"count":10}}'
        html = '<script>self.__next_f.push([1,' + json.dumps("x" + data + "y") + '])</script>'
        objs = lounges._objects(lounges._payload(html), '{"key":', "loungeCode")
        self.assertEqual(objs[0]["ratings"]["average"], 3.8)


if __name__ == "__main__":
    unittest.main()
