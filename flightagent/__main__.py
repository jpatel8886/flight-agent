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
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import notify
from .engine import Searcher

log = logging.getLogger("flightagent")
HISTORY_POINTS = 600


def search_key(s: dict) -> str:
    raw = f"{s['origin']}-{s['destination']}-{s['date']}"
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


def summary(o: dict) -> str:
    stops = o["stops"]
    return f"{o['price']:.0f}, {o['total_minutes'] // 60}h, {stops} stop{'s' if stops != 1 else ''}"


def decide_alert(s: dict, best: dict, cheapest: dict, st: dict, alerts: dict, now: datetime) -> str | None:
    """`best` is the top-ranked (best value) option; alerts track its score, not raw price."""
    prev = st.get("best_score")
    target = s.get("target_price")
    today = now.date().isoformat()
    if prev is None:
        return "first result"
    if best["score"] <= prev - float(alerts.get("min_drop", 10)):
        was = f" (was {st['best_summary']})" if st.get("best_summary") else ""
        return f"better option: {summary(best)}{was}"
    if target and cheapest["price"] <= target and st.get("last_target_alert") != today:
        st["last_target_alert"] = today
        return f"{cheapest['price']:.0f} is at/below your target of {target}"
    hour = alerts.get("daily_digest_utc_hour")
    if hour is not None and now.hour >= int(hour) and st.get("last_digest") != today:
        st["last_digest"] = today
        return "daily summary"
    return None


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
    latest = {"generated_at": now.isoformat(timespec="seconds"), "currency": cfg.get("currency", "USD"), "searches": []}

    for s in cfg["searches"]:
        key = search_key(s)
        meta = {"key": key, "name": s.get("name", key), "origin": s["origin"], "destination": s["destination"], "date": str(s["date"])}
        if Date.fromisoformat(str(s["date"])) < now.date():
            log.info("skipping %s: date has passed", meta["name"])
            continue
        log.info("searching %s", meta["name"])
        results, stats = searcher.run(s)
        options = [serialize(i) for i in results[: int(cfg.get("top_n", 20))]]
        cheapest = min(results, key=lambda i: i.price, default=None)
        if cheapest is not None and all(o["key"] != cheapest.key for o in options):
            options.append(serialize(cheapest))  # always show the cheapest, even if it ranks low
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

        best = options[0]
        low = min(options, key=lambda o: o["price"])
        entry["cheapest_key"] = low["key"]
        hist = history.setdefault(key, [])
        hist.append({"t": latest["generated_at"], "best": best["price"], "cheapest": low["price"], "by_strategy": by_strategy})
        del hist[:-HISTORY_POINTS]
        st = state.setdefault(key, {})
        entry["all_time_low"] = min(low["price"], st.get("lowest_price", low["price"]))

        reason = decide_alert(s, best, low, st, alerts, now)
        if best["score"] < st.get("best_score", float("inf")):
            st.update(best_score=best["score"], best_summary=summary(best), best_seen_at=latest["generated_at"])
        st["lowest_price"] = entry["all_time_low"]
        if reason and alerts.get("email", True) and not args.no_email:
            try:
                notify.send(*notify.render(meta, options, reason, site_url))
            except Exception as e:  # don't lose the run's data because SMTP failed
                log.error("email failed: %s", type(e).__name__)
                entry["errors"].append(f"email: {type(e).__name__}")

    (data_dir / "latest.json").write_text(json.dumps(latest, indent=1))
    (data_dir / "history.json").write_text(json.dumps(history))
    (data_dir / "state.json").write_text(json.dumps(state, indent=1))
    log.info("wrote %s", data_dir)


if __name__ == "__main__":
    main()
