import unittest
from unittest import mock

from flightagent import engine
from flightagent.engine import Searcher
from flightagent.models import Itinerary, Link, Segment

T = {"date": "2027-01-08", "tickets": [["WY202", "WY405"], ["MS981"]], "flights": [
    {"number": "WY202", "from": "BOM", "to": "MCT", "depart": "10:35"},
    {"number": "WY405", "from": "MCT", "to": "CAI", "depart": "14:30"},
    {"number": "MS981", "from": "CAI", "to": "IAD", "depart": "23:55"}]}


def it(price, legs, source="x", sellers=None):
    return Itinerary(source=source, strategy="direct", price=price, currency="USD", sellers=sellers or {},
                     links=[Link("Google Flights", "https://g")],
                     segments=[Segment(o, d, f"2027-01-0{dd}T{t}", f"2027-01-0{dd}T{t}", flight_number=n) for o, d, t, dd, n in legs])


class TrackTest(unittest.TestCase):
    def test_sellers_and_airline_direct_total(self):
        sk = [it(956, [("BOM", "MCT", "10:35", 8, "WY202"), ("MCT", "CAI", "14:30", 8, "WY405"), ("CAI", "IAD", "23:55", 8, "MS981")],
                 sellers={"Gotogate": 956.36, "Skyscanner": 949.66}),
              it(800, [("BOM", "DOH", "02:00", 8, "QR555"), ("DOH", "IAD", "08:00", 8, "QR707")])]  # other flights: ignored
        g1 = [it(559, [("BOM", "MCT", "10:35", 8, ""), ("MCT", "CAI", "14:30", 8, "")]),
              it(439, [("BOM", "MCT", "05:25", 8, ""), ("MCT", "CAI", "14:30", 8, "")])]  # wrong departure time
        g2 = [it(1136, [("CAI", "IAD", "23:55", 8, "")])]

        def fake(self, provider, o, d, day, **kw):
            if provider is engine.skiplagged:
                return sk
            return g1 if d == "CAI" else g2
        with mock.patch.object(Searcher, "_call", fake):
            r = Searcher({}).track(T)
        self.assertEqual(r["best"], {"seller": "Skyscanner", "price": 949.66})
        self.assertEqual(r["sellers"]["Airlines direct (Google Flights)"], 559 + 1136)
        self.assertEqual(list(r["sellers"])[0], "Skyscanner")  # sorted cheapest first


if __name__ == "__main__":
    unittest.main()
