"""Run every configured search, write dashboard data, and send alerts.

    python -m flightagent [--config config.yaml] [--data docs/data] [--no-email]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import notify
from .engine import Searcher
from .geo import country
from .lounges import Lounges

log = logging.getLogger("flightagent")
HISTORY_POINTS = 600


def search_key(s: dict) -> str:
    when = f"arrive{s['arrive']}" if "arrive" in s else s["date"]
    raw = f"{s['origin']}-{s['destination']}-{when}"
    return re.sub(r"[^A-Za-z0-9-]+", "", raw.replace(",", "_"))


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def serialize(it) -> dict:
    d = it.to_dict()
    d.pop("tickets", None)
    d["ticket_links"] = [
        {"leg": f"{t.origin} → {t.destination}", "price": t.price, "links": [l.__dict__ for l in t.links]} for t in it.tickets
    ]
    return d


def avoided(o: dict, avoid: set[str]) -> bool:
    """True if any layover is in a country from avoid_countries (lowercased)."""
    return any((country(c) or "").lower() in avoid for c in o["layovers"])


def summary(o: dict) -> str:
    stops = o["stops"]
    return f"{o['price']:.0f}, {o['total_minutes'] // 60}h, {stops} stop{'s' if stops != 1 else ''}"


def email_slot(now: datetime, alerts: dict) -> str:
    """Identify the current send window, e.g. "2026-10-15T12" = the window that opened at 12:00 local."""
    local = now + timedelta(hours=float(alerts.get("utc_offset_hours", 0)))
    hours = sorted(int(h) for h in alerts.get("send_hours_local", [7, 12, 17, 21]))
    passed = [h for h in hours if h <= local.hour]
    if passed:
        return f"{local.date().isoformat()}T{passed[-1]:02d}"
    return f"{(local.date() - timedelta(days=1)).isoformat()}T{hours[-1]:02d}"


def change_note(best: dict, cheapest: dict, s: dict, st: dict) -> str:
    """Describe what moved since the last email for this search."""
    notes = []
    prev = st.get("emailed_score")
    if prev is None:
        notes.append("first result")
    elif best["score"] < prev - 1:
        notes.append(f"better than last email (was {st.get('emailed_summary', '?')})")
    elif best["score"] > prev + 1:
        notes.append(f"worse than last email (was {st.get('emailed_summary', '?')})")
    else:
        notes.append("no change since last email")
    if s.get("target_price") and cheapest["price"] <= s["target_price"]:
        notes.append(f"cheapest {cheapest['price']:.0f} is at/below your target of {s['target_price']}")
    return "; ".join(notes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="docs/data")
    ap.add_argument("--no-email", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = yaml.safe_load(Path(args.config).read_text())
    data_dir = Path(args.data)
    data_dir.mkdir(parents=True, exist_ok=True)
    history = load_json(data_dir / "history.json", {})
    state = load_json(data_dir / "state.json", {})
    alerts = cfg.get("alerts", {})
    site_url = os.environ.get("SITE_URL")
    now = datetime.now(timezone.utc)
    searcher = Searcher(cfg)
    lounges = Lounges(data_dir / "lounges.json", cfg)
    digest: list[dict] = []
    avoid = {c.lower() for c in cfg.get("avoid_countries", [])}
    latest = {"generated_at": now.isoformat(timespec="seconds"), "currency": cfg.get("currency", "USD"),
              "avoid_countries": cfg.get("avoid_countries", []), "searches": []}

    for s in cfg["searches"]:
        key = search_key(s)
        reverse = "arrive" in s  # "arrive" = work backwards from flights landing on these dates
        days = sorted(str(d) for d in (s["arrive"] if isinstance(s.get("arrive"), list) else [s.get("arrive", s.get("date"))]))
        meta = {"key": key, "name": s.get("name", key), "origin": s["origin"], "destination": s["destination"],
                "date": days[0], "arrive": days if reverse else None}
        if Date.fromisoformat(days[-1]) < now.date():
            log.info("skipping %s: date has passed", meta["name"])
            continue
        log.info("searching %s", meta["name"])
        results, stats = searcher.reverse(s) if reverse else searcher.run(s)
        # Keep the top N overall *and* the top N outside avoid_countries, so the
        # dashboard's "avoid" toggle still has a full list either way.
        n = int(cfg.get("top_n", 20))
        ranked = [serialize(i) for i in results]
        for o in ranked:
            o["layover_countries"] = [country(c) or "" for c in o["layovers"]]
            o["avoid"] = avoided(o, avoid)
        ok = [o for o in ranked if not o["avoid"]]
        keep = {o["key"] for o in ranked[:n]} | {o["key"] for o in ok[:n]}
        for group in (ranked, ok):  # always include the cheapest of each set
            if group:
                keep.add(min(group, key=lambda o: o["price"])["key"])
        options = [o for o in ranked if o["key"] in keep]
        try:
            lounges.annotate(options)
        except Exception as e:  # lounge info is a nice-to-have; never fail the run over it
            log.warning("lounge lookup failed: %s: %s", type(e).__name__, e)
            stats.errors.append(f"lounges: {type(e).__name__}")
        by_strategy = {}
        for i in sorted(results, key=lambda i: i.price):
            by_strategy.setdefault(i.strategy, i.price)
        entry = {
            **meta,
            "target_price": s.get("target_price"),
            "options": options,
            "best_by_strategy": by_strategy,
            "hubs": stats.hubs,
            "requests": stats.requests,
            "errors": stats.errors,
        }
        latest["searches"].append(entry)
        if not options:
            log.warning("no results for %s (%d errors)", meta["name"], len(stats.errors))
            continue

        # Emails and alert tracking use the preferred set (outside avoid_countries) when it has fares.
        pref = [o for o in options if not o["avoid"]] or options
        best, low = pref[0], min(pref, key=lambda o: o["price"])
        entry["cheapest_key"] = min(options, key=lambda o: o["price"])["key"]
        hist = history.setdefault(key, [])
        hist.append({
            "t": latest["generated_at"],
            "best": options[0]["price"],
            "cheapest": min(o["price"] for o in options),
            "best_ok": best["price"] if pref is not options else None,
            "cheapest_ok": low["price"] if pref is not options else None,
        })
        del hist[:-HISTORY_POINTS]
        st = state.setdefault(key, {})
        entry["all_time_low"] = min(low["price"], st.get("lowest_price", low["price"]))

        if best["score"] < st.get("best_score", float("inf")):
            st.update(best_score=best["score"], best_summary=summary(best), best_seen_at=latest["generated_at"])
        st["lowest_price"] = entry["all_time_low"]
        digest.append({**meta, "options": pref, "change": change_note(best, low, s, st), "st": st})

    # Emails go out at most once per send window (default 4/day), however often the search runs.
    slot = email_slot(now, alerts)
    mail = state.setdefault("_email", {})
    if digest and alerts.get("email", True) and not args.no_email and mail.get("last_slot") != slot:
        try:
            if notify.send(*notify.render_digest(digest, site_url)):
                mail["last_slot"] = slot
                for d in digest:
                    d["st"].update(emailed_score=d["options"][0]["score"], emailed_summary=summary(d["options"][0]))
        except Exception as e:  # don't lose the run's data because SMTP failed
            log.error("email failed: %s", type(e).__name__)
            latest["searches"][0]["errors"].append(f"email: {type(e).__name__}")

    (data_dir / "latest.json").write_text(json.dumps(latest, indent=1))
    (data_dir / "history.json").write_text(json.dumps(history))
    (data_dir / "state.json").write_text(json.dumps(state, indent=1))
    lounges.save()
    log.info("wrote %s", data_dir)


if __name__ == "__main__":
    main()
