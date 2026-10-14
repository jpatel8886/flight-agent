"""Skiplagged's public search endpoint (unofficial; no API key).

Surfaces virtual-interlined (Kiwi) fares and hidden-city fares that other
sites don't sell.
"""

from __future__ import annotations

import logging
import time

from primp import Client

from ..links import search_links
from ..models import Itinerary, Segment

log = logging.getLogger(__name__)
NAME = "Skiplagged"
URL = "https://skiplagged.com/api/search.php"


def _local(ts: str) -> str:
    # "2026-12-15T16:05:00-08:00" -> "2026-12-15T16:05" (keep airport-local time)
    return ts[:16]


def search(origin: str, dest: str, day: str, *, currency: str, adults: int, cabin: str, **_) -> list[Itinerary]:
    if currency != "USD":
        log.info("skiplagged: prices are USD only; skipping for %s", currency)
        return []
    client = Client(impersonate="chrome_145", impersonate_os="macos", cookie_store=True, referer=True)
    params = {"from": origin, "to": dest, "depart": day, "return": "", "format": "v3", "counts[adults]": str(adults)}
    data: dict = {}
    for attempt in range(3):
        r = client.get(URL, params=params, timeout=30)
        if r.status_code != 200 or not r.text.startswith("{"):
            raise RuntimeError(f"skiplagged HTTP {r.status_code} (likely bot-check)")
        data = r.json()
        if not data.get("incomplete"):
            break
        time.sleep(2 + attempt * 2)  # results stream in; poll again for a fuller set

    flights = data.get("flights") or {}
    names = {k: v.get("name", k) for k, v in (data.get("airlines") or {}).items()}
    out = []
    for it in (data.get("itineraries") or {}).get("outbound") or []:
        f = flights.get(it.get("flight"))
        price = it.get("one_way_price")
        if not f or not price:
            continue
        segs = [
            Segment(
                origin=s["departure"]["airport"],
                destination=s["arrival"]["airport"],
                depart=_local(s["departure"]["time"]),
                arrive=_local(s["arrival"]["time"]),
                carrier=s.get("airline", ""),
                flight_number=f"{s.get('airline', '')}{s.get('flight_number', '')}",
                duration_min=int(s.get("duration", 0)) // 60,
            )
            for s in f.get("segments", [])
        ]
        if not segs:
            continue
        hidden = segs[-1].destination != dest
        if hidden:
            # Ticket continues past our destination: truncate to the part we fly.
            idx = next((i for i, s in enumerate(segs) if s.destination == dest), None)
            if idx is None:
                continue
            segs = segs[: idx + 1]
        notes = []
        if it.get("vi"):
            notes.append("Virtual interlining: separate airline tickets combined by the seller")
        if hidden:
            notes.append(f"Hidden-city fare: ticket is to a further city; carry-on only, don't check bags")
        out.append(
            Itinerary(
                source=NAME,
                strategy="hidden-city" if hidden else "direct",
                price=price / 100.0,
                currency="USD",
                segments=segs,
                airlines=sorted({names.get(s.carrier, s.carrier) for s in segs}),
                separate_tickets=bool(it.get("vi")),
                hidden_city=hidden,
                links=search_links(origin, dest, day, adults),
                notes=notes,
            )
        )
    return out
