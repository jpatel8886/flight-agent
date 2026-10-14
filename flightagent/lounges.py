"""Priority Pass lounge lookup for layover airports, cached in docs/data/lounges.json.

Data comes from the public prioritypass.com pages (robots.txt allows these;
the /api paths it disallows are not used). Priority Pass publishes member
star ratings and rating counts, not written reviews.

- Airport index (IATA -> page) is built from the per-country pages listed in
  the sitemap, then cached for INDEX_TTL_DAYS.
- Each airport's lounges are fetched the first time it shows up as a layover and
  cached for AIRPORT_TTL_DAYS. Lounge detail pages (airside/landside, location)
  are fetched within a per-run budget so a cold cache fills over a few runs.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from primp import Client

log = logging.getLogger(__name__)
BASE = "https://www.prioritypass.com"
INDEX_TTL_DAYS = 90
AIRPORT_TTL_DAYS = 30
KEEP = {"LOUNGE", "REST"}  # skip spas, fast track, restaurants ("REFRESH"), gaming ("UNWIND")
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)


def _payload(html: str) -> str:
    """Next.js streams page data as escaped JS strings; join and unescape them."""
    return "".join(json.loads(f'"{c}"') for c in _PUSH.findall(html))


def _objects(txt: str, start: str, must: str) -> list[dict]:
    dec, out = json.JSONDecoder(), []
    for m in re.finditer(re.escape(start), txt):
        try:
            obj, _ = dec.raw_decode(txt, m.start())
        except json.JSONDecodeError:
            continue
        if must in obj:
            out.append(obj)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stale(ts: str | None, days: int) -> bool:
    return not ts or datetime.fromisoformat(ts) < _now() - timedelta(days=days)


class Lounges:
    def __init__(self, path: Path, cfg: dict):
        self.path = path
        c = cfg.get("lounges", {})
        self.enabled = c.get("enabled", True)
        self.budget = int(c.get("max_fetches_per_run", 80))
        self.delay = max(2.0, float(cfg.get("request_delay_seconds", 1.5)))  # be gentle: the site rate-limits bursts
        try:
            self.cache = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}
        self.cache.setdefault("index", {})
        self.cache.setdefault("airports", {})
        self._client = None

    def _get(self, url: str) -> str | None:
        if self.budget <= 0:
            return None
        self.budget -= 1
        self._client = self._client or Client(impersonate="chrome_145", impersonate_os="macos", cookie_store=True, referer=True)
        try:
            r = self._client.get(url, timeout=30)
        except Exception as e:  # network hiccup: retry on a later run
            log.warning("lounges: %s: %s", url, type(e).__name__)
            return None
        finally:
            time.sleep(self.delay)
        return r.text if r.status_code == 200 else None

    def _ensure_index(self) -> None:
        idx = self.cache["index"]
        if _stale(idx.get("built"), INDEX_TTL_DAYS) or not idx.get("airports"):
            sitemap = self._get(f"{BASE}/sitemap.xml")
            if not sitemap:
                return
            todo = sorted(set(re.findall(r"<loc>(https://www\.prioritypass\.com/en-GB/lounges/[a-z0-9-]+)</loc>", sitemap)))
        else:
            todo = idx.get("missing", [])  # countries that failed last time
        if not todo:
            return
        # Indexing ~145 countries happens once per INDEX_TTL_DAYS; it gets its own budget.
        self.budget += len(todo)
        airports, missing = dict(idx.get("airports", {})), []
        for url in todo:
            html = self._get(url)
            if not html:
                missing.append(url)
                continue
            for a in _objects(_payload(html), '{"name":', "airportSlug"):
                if a.get("iata") and a.get("countrySlug"):
                    airports[a["iata"]] = {"name": a.get("name", ""), "path": f"/lounges/{a['countrySlug']}/{a['airportSlug']}"}
        built = idx.get("built") if idx.get("airports") and not _stale(idx.get("built"), INDEX_TTL_DAYS) else _now().isoformat(timespec="seconds")
        self.cache["index"] = {"built": built, "airports": airports, "missing": missing}
        log.info("lounges: indexed %d airports (%d countries fetched, %d to retry)", len(airports), len(todo) - len(missing), len(missing))

    def _airport(self, iata: str) -> dict | None:
        cached = self.cache["airports"].get(iata)
        if cached and not _stale(cached.get("fetched"), AIRPORT_TTL_DAYS) and cached.get("complete"):
            return cached
        entry = self.cache["index"].get("airports", {}).get(iata)
        if not entry:
            return None  # no Priority Pass presence (or index not built yet)
        if not cached or _stale(cached.get("fetched"), AIRPORT_TTL_DAYS):
            html = self._get(BASE + entry["path"])
            if not html:
                return cached
            lounges = []
            for o in _objects(_payload(html), '{"key":', "loungeCode"):
                if o.get("outletCategory") not in KEEP:
                    continue
                r = o.get("ratings") or {}
                lounges.append({
                    "code": o["loungeCode"],
                    "name": o.get("name", ""),
                    "category": o["outletCategory"],
                    "terminal": o.get("terminalName", ""),
                    "hours": o.get("openHours", ""),
                    "rating": r.get("average") or None,
                    "ratings_count": r.get("count", 0),
                    "url": f"{BASE}{entry['path']}/{o.get('slug', '')}",
                    "airside": None,
                    "location": "",
                })
            cached = {"name": entry["name"], "url": BASE + entry["path"], "fetched": _now().isoformat(timespec="seconds"), "lounges": lounges}
            self.cache["airports"][iata] = cached
        # Details tell us airside vs landside: a landside lounge is unusable on a connection.
        for lg in cached["lounges"]:
            if lg["airside"] is None and lg["category"] == "LOUNGE":
                html = self._get(lg["url"])
                if not html:
                    break
                loc = next((o for o in _objects(_payload(html), '{"city":', "description")), None)
                desc = (loc or {}).get("description", "")
                lg["location"] = desc[:300]
                if re.match(r"\s*landside", desc, re.I):
                    lg["airside"] = False
                elif re.match(r"\s*airside", desc, re.I):
                    lg["airside"] = True
                else:
                    lg["airside"] = "unknown"
        cached["complete"] = all(lg["airside"] is not None for lg in cached["lounges"] if lg["category"] == "LOUNGE")
        return cached

    def summary(self, iata: str) -> dict | None:
        a = self._airport(iata)
        if not a:
            return None
        usable = [l for l in a["lounges"] if l["category"] == "LOUNGE" and l["airside"] is not False]
        if not usable:
            return None
        top = max(usable, key=lambda l: ((l["rating"] or 0), l["ratings_count"]))
        return {
            "airport": a["name"],
            "url": a["url"],
            "count": len(usable),
            "sleep_pods": sum(1 for l in a["lounges"] if l["category"] == "REST"),
            "best": {k: top[k] for k in ("name", "terminal", "hours", "rating", "ratings_count", "url")},
            "lounges": [{k: l[k] for k in ("name", "terminal", "hours", "rating", "ratings_count", "url", "airside")} for l in usable],
        }

    def annotate(self, options: list[dict]) -> None:
        """Add `lounges` = {layover IATA: summary} to each serialized itinerary."""
        if not self.enabled:
            return
        self._ensure_index()
        seen: dict[str, dict | None] = {}
        for o in options:
            found = {}
            for code in dict.fromkeys(o["layovers"]):
                if code not in seen:
                    seen[code] = self.summary(code)
                if seen[code]:
                    found[code] = seen[code]
            o["lounges"] = found

    def save(self) -> None:
        self.path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
