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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta
from itertools import product

from .models import Itinerary
from .providers import google_flights, serpapi, skiplagged

log = logging.getLogger(__name__)


class Ranker:
    """Ranks by "effective cost": price plus what travel time, stops and risk are worth to you.

    With the defaults, a 26h one-stop fare at 900 beats a 40h two-stop fare at 820.
    """

    def __init__(self, cfg: dict):
        r = cfg.get("ranking", {})
        self.per_hour = float(r.get("value_per_hour", 15))
        self.per_stop = float(r.get("per_stop_penalty", 40))
        self.separate = float(r.get("separate_ticket_penalty", 75))
        self.hidden = float(r.get("hidden_city_penalty", 50))

    def score(self, i: Itinerary) -> float:
        return (
            i.price
            + self.per_hour * i.total_minutes / 60
            + self.per_stop * i.stops
            + (self.separate if i.separate_tickets else 0)
            + (self.hidden if i.hidden_city else 0)
        )

    def rank(self, items: list[Itinerary], n: int | None = None) -> list[Itinerary]:
        for i in items:
            i.score = round(self.score(i), 1)
        return sorted(items, key=lambda i: (i.score, i.price))[:n]


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
        self.ranker = Ranker(cfg)
        self._cache: dict[tuple, list[Itinerary]] = {}
        # Lookups to different sites run side by side; each site gets a small concurrency cap
        # so we stay under its throttling.
        par = cfg.get("parallel", {})
        self._limits = {
            google_flights.NAME: threading.Semaphore(int(par.get("google_flights", 3))),
            skiplagged.NAME: threading.Semaphore(int(par.get("skiplagged", 2))),
            serpapi.NAME: threading.Semaphore(int(par.get("serpapi", 1))),
        }
        self._lock = threading.Lock()

    def _call(self, provider, origin, dest, day, **kw) -> list[Itinerary]:
        ck = (provider.NAME, origin, dest, day, tuple(kw.get("via") or ()), tuple(kw.get("airlines") or ()), kw.get("max_stops"))
        if ck in self._cache:
            return self._cache[ck]
        with self._limits.get(provider.NAME, threading.Semaphore(1)):
            if ck in self._cache:  # another thread fetched it while we waited
                return self._cache[ck]
            for attempt in range(2):
                try:
                    with self._lock:
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
            time.sleep(self.delay + random.uniform(0, self.delay))  # pace each slot
            self._cache[ck] = res
        return res

    def _prefetch(self, calls: list[tuple]) -> None:
        """Run independent lookups concurrently to fill the cache; callers then read from it."""
        calls = [c for c in dict.fromkeys(calls)]
        if len(calls) < 2:
            return
        workers = max(1, sum(int(v) for v in (self.cfg.get("parallel") or {"google_flights": 3, "skiplagged": 2}).values()))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda c: self._call(c[0], c[1], c[2], c[3], **dict(c[4])), calls))

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
        banned = {a.upper() for a in self.cfg.get("exclude_airports", [])}
        hubs = [h for h in self.cfg.get("hubs", []) if h not in origins + dests and h not in banned]
        strat = self.cfg.get("strategies", {})
        found: list[Itinerary] = []

        google_pairs = set()  # pairs Google can route at all; forced-hub is pointless elsewhere
        self._prefetch([(p, o, d, day, ()) for o, d in product(origins, dests) for p in self._providers()])
        for o, d in product(origins, dests):
            for prov in self._providers():
                res = self._call(prov, o, d, day)
                if prov is google_flights and res:
                    google_pairs.add((o, d))
                found += self._fits(res)
        if self.cfg.get("providers", {}).get("google_flights", True) and strat.get("forced_hub", True):
            self._prefetch([(google_flights, o, d, day, (("via", (h,)), ("strategy", "forced-hub")))
                            for o, d, h in product(origins, dests, hubs) if (o, d) in google_pairs])
            for o, d, h in product(origins, dests, hubs):
                if (o, d) not in google_pairs:
                    continue
                res = self._call(google_flights, o, d, day, via=(h,), strategy="forced-hub")
                # Google treats the hub as a preference; keep only true matches.
                res = self._fits([i for i in res if h in i.layovers])
                self._hub(h)["forced"] = min((i.price for i in res), default=None)
                found += res
        if strat.get("self_transfer", True):
            for o, d in product(origins, dests):
                best = self.ranker.rank(found, 1)
                found += self._self_transfer(o, d, day, hubs, best_score=best[0].score if best else float("inf"))

        return self.ranker.rank(merge(found)), self.stats

    def track(self, t: dict) -> dict:
        """Price one specific itinerary (by flight number) across every source that sells it.

        Skiplagged reports per-seller prices for the exact flights (Gotogate, Mytrip, ...).
        Google Flights prices each separately-sold ticket at the airline, matched by
        departure time since its results carry no flight numbers.
        """
        self.stats = RunStats()
        day = str(t["date"])
        flights = t["flights"]
        numbers = [f["number"].upper() for f in flights]
        sellers: dict[str, float] = {}
        links: list[dict] = []
        for it in self._call(skiplagged, flights[0]["from"], flights[-1]["to"], day):
            if [s.flight_number.upper() for s in it.segments] == numbers:
                sellers.update(it.sellers or {skiplagged.NAME: it.price})
                links = [l.__dict__ for l in it.links]
        by_num = {f["number"].upper(): f for f in flights}
        legs = []
        for group in t.get("tickets") or [numbers]:
            fs = [by_num[n.upper()] for n in group]
            res = self._call(google_flights, fs[0]["from"], fs[-1]["to"], day,
                             via=tuple(f["to"] for f in fs[:-1]), airlines=tuple(sorted({f["number"][:2] for f in fs})),
                             max_stops=len(fs) - 1)
            match = [i for i in res if [(s.origin, s.destination, s.depart[11:16]) for s in i.segments]
                     == [(f["from"], f["to"], f["depart"]) for f in fs]]
            legs.append({"flights": [f["number"] for f in fs], "price": min((i.price for i in match), default=None),
                         "url": match[0].links[0].url if match and match[0].links else None})
        if legs and all(l["price"] for l in legs):
            sellers["Airlines direct (Google Flights)"] = sum(l["price"] for l in legs)
        best = min(sellers.items(), key=lambda kv: kv[1], default=None)
        return {"sellers": dict(sorted(sellers.items(), key=lambda kv: kv[1])), "best": best and {"seller": best[0], "price": best[1]},
                "google_tickets": legs, "links": links, "requests": self.stats.requests, "errors": self.stats.errors}

    def _fits(self, items: list[Itinerary], slack_min: float = 0, slack_stops: int = 0) -> list[Itinerary]:
        """Drop itineraries over max_trip_hours / max_layovers, minus what a later leg will add."""
        limit = float(self.cfg.get("max_trip_hours", 40)) * 60 - slack_min
        stops = int(self.cfg.get("max_layovers", 2)) - slack_stops
        max_lay = float(self.cfg.get("max_layover_hours", 24)) * 60
        banned = {a.upper() for a in self.cfg.get("exclude_airports", [])}
        return [
            i for i in items
            if i.total_minutes <= limit
            and i.stops <= stops
            and all(m < max_lay for m in i.layover_minutes)
            and not banned & set(i.layovers)
        ]

    def _hub(self, h: str) -> dict:
        return self.stats.hubs.setdefault(h, {"forced": None, "self_transfer": None, "skipped": False})

    def _self_transfer(self, o: str, d: str, day: str, hubs: list[str], best_score: float) -> list[Itinerary]:
        st = self.cfg.get("self_transfer", {})
        min_conn = int(st.get("min_connection_minutes", 180))
        # The ticket change is a layover too, so it obeys the global cap as well.
        max_lay = min(float(st.get("max_layover_hours", 24)), float(self.cfg.get("max_layover_hours", 24))) * 60
        n = int(st.get("legs_per_hub", 6))
        out = []
        self._prefetch([(google_flights, o, h, day, ()) for h in hubs])
        second = []
        for h in hubs:
            leg1 = self.ranker.rank(merge(self._fits(self._call(google_flights, o, h, day), slack_min=min_conn, slack_stops=1)), n)
            if leg1 and leg1[0].score + self.ranker.per_stop + self.ranker.separate + self.ranker.per_hour * min_conn / 60 < best_score:
                arr = sorted({i.segments[-1].arrive[:10] for i in leg1})
                second += [(google_flights, h, d, d2, ()) for d2 in sorted(set(arr) | {str(Date.fromisoformat(arr[-1]) + timedelta(days=1))})[:3]]
        self._prefetch(second)
        for h in hubs:
            leg1 = self.ranker.rank(merge(self._fits(self._call(google_flights, o, h, day), slack_min=min_conn, slack_stops=1)), n)
            if not leg1:
                continue
            # Lower bound for any pairing: leg 1 plus the hub stop, the separate-ticket
            # penalty and the minimum connection time (leg 2 only adds to it).
            bound = leg1[0].score + self.ranker.per_stop + self.ranker.separate + self.ranker.per_hour * min_conn / 60
            if bound >= best_score:
                self._hub(h)["skipped"] = True
                log.info("self-transfer via %s skipped: lower bound %.0f >= best %.0f", h, bound, best_score)
                continue
            # Second-leg dates follow from when the first leg actually lands.
            arrivals = sorted({i.segments[-1].arrive[:10] for i in leg1})
            days2 = sorted(set(arrivals) | {str(Date.fromisoformat(arrivals[-1]) + timedelta(days=1))})[:3]
            leg2 = self.ranker.rank(merge(self._fits([i for d2 in days2 for i in self._call(google_flights, h, d, d2)], slack_stops=1)), n * 2)
            combos = []
            for a, b in product(leg1, leg2):
                if a.destination != b.origin:
                    continue
                gap = (b.segments[0].depart_dt - a.segments[-1].arrive_dt).total_seconds() / 60
                if min_conn <= gap <= max_lay:
                    combos.append(_combine(a, b, h, gap))
            combos = self.ranker.rank(self._fits(combos), n)
            self._hub(h)["self_transfer"] = min((c.price for c in combos), default=None)
            if combos:
                best_score = min(best_score, combos[0].score)
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


def _as_list(v) -> list[str]:
    return [x.upper() for x in (v if isinstance(v, list) else [v])]

