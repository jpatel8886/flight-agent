"""Common itinerary model shared by every provider and strategy.

Times are kept as naive *local* ISO strings ("2026-12-15T16:05"). Comparing two
times is only valid at the same airport, which is all the combinator needs.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Segment:
    origin: str
    destination: str
    depart: str  # local ISO, minutes precision
    arrive: str
    carrier: str = ""
    flight_number: str = ""
    duration_min: int = 0

    @property
    def depart_dt(self) -> datetime:
        return datetime.fromisoformat(self.depart)

    @property
    def arrive_dt(self) -> datetime:
        return datetime.fromisoformat(self.arrive)


@dataclass
class Link:
    name: str
    url: str


@dataclass
class Itinerary:
    source: str  # provider that priced it, e.g. "Google Flights"
    strategy: str  # "direct" | "forced-hub" | "self-transfer" | "hidden-city"
    price: float
    currency: str
    segments: list[Segment]
    airlines: list[str] = field(default_factory=list)
    via: str = ""  # hub the strategy targeted, if any
    separate_tickets: bool = False
    hidden_city: bool = False
    links: list[Link] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    also_seen: dict[str, float] = field(default_factory=dict)  # other sources -> price
    tickets: list["Itinerary"] = field(default_factory=list)  # for self-transfer
    score: float = 0.0  # ranking cost: price plus time/stop penalties (lower is better)
    sellers: dict[str, float] = field(default_factory=dict)  # booking site -> price, when the source reports it

    @property
    def origin(self) -> str:
        return self.segments[0].origin

    @property
    def destination(self) -> str:
        return self.segments[-1].destination

    @property
    def stops(self) -> int:
        return len(self.segments) - 1

    @property
    def total_minutes(self) -> int:
        """Flight time plus ground time; gaps are measured at a single airport so local times are comparable."""
        total = sum(s.duration_min for s in self.segments)
        for a, b in zip(self.segments, self.segments[1:]):
            total += max(0, int((b.depart_dt - a.arrive_dt).total_seconds() // 60))
        return total

    @property
    def layover_minutes(self) -> list[int]:
        return [int((b.depart_dt - a.arrive_dt).total_seconds() // 60) for a, b in zip(self.segments, self.segments[1:])]

    @property
    def layovers(self) -> list[str]:
        return [s.destination for s in self.segments[:-1]]

    @property
    def key(self) -> str:
        """Identity of the physical flights, independent of who sold them."""
        raw = "|".join(f"{s.origin}{s.destination}{s.depart}" for s in self.segments)
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(
            key=self.key,
            origin=self.origin,
            destination=self.destination,
            stops=self.stops,
            total_minutes=self.total_minutes,
            layovers=self.layovers,
        )
        return d


def iso_local(y_m_d: tuple, h_m: tuple) -> str:
    y, m, d = y_m_d
    h, mi = h_m
    return f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}"
