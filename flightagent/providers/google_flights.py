"""Google Flights via the unofficial `fast-flights` scraper (no API key)."""

from __future__ import annotations

import logging
import time

from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query, get_flights

from ..links import search_links
from ..models import Itinerary, Segment, iso_local

log = logging.getLogger(__name__)
NAME = "Google Flights"


def search(
    origin: str,
    dest: str,
    day: str,
    *,
    currency: str,
    adults: int,
    cabin: str,
    via: list[str] | tuple[str, ...] | None = None,
    strategy: str = "direct",
) -> list[Itinerary]:
    q = create_query(
        flights=[FlightQuery(date=day, from_airport=origin, to_airport=dest, connecting_airports=list(via) if via else None)],
        trip="one-way",
        seat=cabin,
        passengers=Passengers(adults=adults),
        currency=currency,
        language="en",
    )
    results = []
    for attempt in range(2):
        try:
            results = get_flights(q)
            break
        except FlightsNotFound:
            return []
        except (TypeError, IndexError, AttributeError):
            # Empty payload: either no such routing or an intermittent soft-throttle; retry once.
            log.debug("google: empty result for %s-%s via %s (attempt %d)", origin, dest, via, attempt + 1)
            time.sleep(4)

    url = q.url()
    out = []
    for f in results:
        if not f.price or not f.flights:
            continue
        segs = [
            Segment(
                origin=s.from_airport.code,
                destination=s.to_airport.code,
                depart=iso_local(s.departure.date, s.departure.time),
                arrive=iso_local(s.arrival.date, s.arrival.time),
                duration_min=s.duration or 0,
            )
            for s in f.flights
        ]
        out.append(
            Itinerary(
                source=NAME,
                strategy=strategy,
                price=float(f.price),
                currency=currency,
                segments=segs,
                airlines=list(f.airlines),
                via=via[0] if via else "",
                links=search_links(origin, dest, day, adults, google_url=url),
            )
        )
    return out
