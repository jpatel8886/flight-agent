"""IATA airport -> country, from the OpenFlights airport dataset (flightagent/data/airport_countries.json)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _countries() -> dict[str, str]:
    return json.loads((Path(__file__).parent / "data" / "airport_countries.json").read_text())


def country(iata: str) -> str | None:
    return _countries().get(iata.upper())
