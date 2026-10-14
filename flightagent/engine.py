"""Search orchestration.

1. Direct: ask each provider for origin -> destination.
2. Forced hub: single ticket, Google Flights constrained to connect via each hub.
3. Self-transfer: price origin -> hub and hub -> destination separately and pair
   legs that connect. A hub is skipped early when its first leg alone already
   costs more than the best fare found so far (no pairing could win).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta
from itertools import product

from .models import Itinerary
from .providers import google_flights, serpapi, skiplagged

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    hubs: dict[str, dict] = field(default_factory=dict)  # hub -> {forced, self_transfer, skipped}


class Searcher:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.common = dict(currency=cfg.get("currency", "USD"), adults=cfg.get("adults", 1), cabin=cfg.get("cabin", "economy"))
        self.delay = float(cfg.get("request_delay_seconds", 1.5))
        self.stats = RunStats()
        self._cache: dict[tuple, list[Itinerary]] = {}

    def _call(self, provider, origin, dest, day, **kw) -> list[Itinerary]:
        ck = (provider.NAME, origin, dest, day, tuple(kw.get("via") or ()))
        if ck in self._cache:
            return self._cache[ck]
        for attempt in range(2):
            try:
                self.stats.requests += 1
                res = provider.search(origin, dest, day, **self.common, **kw)
                break
            except Exception as e:  # providers are unofficial; one failing must not sink the run
                if attempt == 1:
                    msg = f"{provider.NAME} {origin}-{dest} {day}: {type(e).__name__}: {e}"
                    log.warning(msg)
                    self.stats.errors.append(msg[:300])
                    res = []
                time.sleep(self.delay * 3)
        time.sleep(self.delay + random.uniform(0, self.delay))
        self._cache[ck] = res
        return res

    def _providers(self) -> list:
        p = self.cfg.get("providers", {})
        out = []
        if p.get("google_flights", True):
            out.append(google_flights)
        if p.get("skiplagged", True):
            out.append(skiplagged)
        sp = p.get("serpapi", "auto")
        if sp is True or (sp == "auto" and serpapi.available()):
            out.append(serpapi)
        return out

    def run(self, search: dict) -> tuple[list[Itinerary], RunStats]:
        self.stats = RunStats()
        origins = _as_list(search["origin"])
        dests = _as_list(search["destination"])
        day = str(search["date"])
        hubs = [h for h in self.cfg.get("hubs", []) if h not in origins + dests]
        strat = self.cfg.get("strategies", {})
        found: list[Itinerary] = []

        for o, d in product(origins, dests):
            for prov in self._providers():
                found += self._fits(self._call(prov, o, d, day))
        if self.cfg.get("providers", {}).get("google_flights", True) and strat.get("forced_hub", True):
            for o, d, h in product(origins, dests, hubs):
                res = self._call(google_flights, o, d, day, via=[h], strategy="forced-hub")
                # Google treats the hub as a preference; keep only true matches.
                res = self._fits([i for i in res if h in i.layovers])
                self._hub(h)["forced"] = min((i.price for i in res), default=None)
                found += res
        if strat.get("self_transfer", True):
            for o, d in product(origins, dests):
                found += self._self_transfer(o, d, day, hubs, best_so_far=min((i.price for i in found), default=float("inf")))

        return merge(found), self.stats

    def _fits(self, items: list[Itinerary], slack_min: float = 0) -> list[Itinerary]:
        """Drop itineraries over max_trip_hours (minus slack reserved for a later leg)."""
        limit = float(self.cfg.get("max_trip_hours", 40)) * 60 - slack_min
        return [i for i in items if i.total_minutes <= limit]

    def _hub(self, h: str) -> dict:
        return self.stats.hubs.setdefault(h, {"forced": None, "self_transfer": None, "skipped": False})

    def _self_transfer(self, o: str, d: str, day: str, hubs: list[str], best_so_far: float) -> list[Itinerary]:
        st = self.cfg.get("self_transfer", {})
        min_conn = int(st.get("min_connection_minutes", 180))
        max_lay = float(st.get("max_layover_hours", 24)) * 60
        n = int(st.get("legs_per_hub", 6))
        out = []
        for h in hubs:
            leg1 = _cheapest(self._fits(self._call(google_flights, o, h, day), slack_min=min_conn), n)
            if not leg1:
                continue
            if leg1[0].price >= best_so_far:
                self._hub(h)["skipped"] = True
                log.info("self-transfer via %s skipped: first leg %.0f >= best %.0f", h, leg1[0].price, best_so_far)
                continue
            # Second-leg dates follow from when the first leg actually lands.
            arrivals = sorted({i.segments[-1].arrive[:10] for i in leg1})
            days2 = sorted(set(arrivals) | {str(Date.fromisoformat(arrivals[-1]) + timedelta(days=1))})[:3]
            leg2 = _cheapest([i for d2 in days2 for i in self._call(google_flights, h, d, d2)], n * 2)
            combos = []
            for a, b in product(leg1, leg2):
                if a.destination != b.origin:
                    continue
                gap = (b.segments[0].depart_dt - a.segments[-1].arrive_dt).total_seconds() / 60
                if min_conn <= gap <= max_lay:
                    combos.append(_combine(a, b, h, gap))
            combos = _cheapest(self._fits(combos), n)
            self._hub(h)["self_transfer"] = combos[0].price if combos else None
            if combos:
                best_so_far = min(best_so_far, combos[0].price)
            out += combos
        return out


def _combine(a: Itinerary, b: Itinerary, hub: str, gap_min: float) -> Itinerary:
    hrs = gap_min / 60
    return Itinerary(
        source="Google Flights x2",
        strategy="self-transfer",
        price=a.price + b.price,
        currency=a.currency,
        segments=a.segments + b.segments,
        airlines=sorted(set(a.airlines) | set(b.airlines)),
        via=hub,
        separate_tickets=True,
        links=[],
        notes=[
            f"Two separate tickets with {hrs:.1f}h at {hub}. Book each leg separately; "
            "a delay on leg 1 is not protected. Check transit/visa rules for the hub."
        ],
        tickets=[a, b],
    )


def merge(items: list[Itinerary]) -> list[Itinerary]:
    """Collapse the same physical flights seen via several sources, keeping the cheapest."""
    best: dict[str, Itinerary] = {}
    for it in items:
        cur = best.get(it.key)
        if cur is None:
            best[it.key] = it
            continue
        lo, hi = (it, cur) if it.price < cur.price else (cur, it)
        for src, p in {**hi.also_seen, hi.source: hi.price}.items():
            if src != lo.source:
                lo.also_seen[src] = min(p, lo.also_seen.get(src, p))
        lo.airlines = lo.airlines or hi.airlines
        best[it.key] = lo
    return sorted(best.values(), key=lambda i: (i.price, i.total_minutes))


def _cheapest(items: list[Itinerary], n: int) -> list[Itinerary]:
    return sorted(merge(items), key=lambda i: i.price)[:n]


def _as_list(v) -> list[str]:
    return [x.upper() for x in (v if isinstance(v, list) else [v])]

