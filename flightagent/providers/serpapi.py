"""Google Flights through SerpApi (optional; needs SERPAPI_KEY, free tier ~250 searches/month).

A reliable fallback for when direct scraping gets rate-limited. Only used for
the main origin->destination search to stay inside the free quota.
"""

from __future__ import annotations

import os

from primp import Client

from ..links import safe_url, search_links
from ..models import Itinerary, Segment

NAME = "Google Flights (SerpApi)"
CABINS = {"economy": 1, "premium-economy": 2, "business": 3, "first": 4}


def available() -> bool:
    return bool(os.environ.get("SERPAPI_KEY"))


def search(origin: str, dest: str, day: str, *, currency: str, adults: int, cabin: str, **_) -> list[Itinerary]:
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": day,
        "type": "2",  # one-way
        "currency": currency,
        "hl": "en",
        "adults": str(adults),
        "travel_class": str(CABINS.get(cabin, 1)),
        "api_key": os.environ["SERPAPI_KEY"],
    }
    r = Client().get("https://serpapi.com/search.json", params=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"serpapi HTTP {r.status_code}")
    data = r.json()
    gurl = safe_url((data.get("search_metadata") or {}).get("google_flights_url"))
    out = []
    for opt in (data.get("best_flights") or []) + (data.get("other_flights") or []):
        if not opt.get("price") or not opt.get("flights"):
            continue
        segs = [
            Segment(
                origin=s["departure_airport"]["id"],
                destination=s["arrival_airport"]["id"],
                depart=s["departure_airport"]["time"].replace(" ", "T")[:16],
                arrive=s["arrival_airport"]["time"].replace(" ", "T")[:16],
                carrier=s.get("airline", ""),
                flight_number=s.get("flight_number", ""),
                duration_min=int(s.get("duration", 0)),
            )
            for s in opt["flights"]
        ]
        out.append(
            Itinerary(
                source=NAME,
                strategy="direct",
                price=float(opt["price"]),
                currency=currency,
                segments=segs,
                airlines=sorted({s.carrier for s in segs if s.carrier}),
                links=search_links(origin, dest, day, adults, google_url=gurl),
            )
        )
    return out
