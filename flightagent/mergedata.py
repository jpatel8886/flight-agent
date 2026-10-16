"""Combine this run's docs/data with whatever another run committed meanwhile.

    python -m flightagent.mergedata OURS_DIR REPO_DATA_DIR

Used by the monitor workflow right before pushing: the repo dir has been reset to
the latest main, and OURS_DIR holds this run's output. This run's latest.json
and state.json win (they're the newest); price history and the lounge cache
are unioned so points and lookups from both runs survive.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .__main__ import HISTORY_POINTS


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def merge_history(theirs: dict, ours: dict) -> dict:
    out = {}
    for key in sorted(set(theirs) | set(ours)):
        points = {p["t"]: p for p in theirs.get(key, [])}
        points.update({p["t"]: p for p in ours.get(key, [])})
        out[key] = [points[t] for t in sorted(points)][-HISTORY_POINTS:]
    return out


def merge_lounges(theirs: dict, ours: dict) -> dict:
    out = {**theirs, **ours}
    idx_t, idx_o = theirs.get("index", {}), ours.get("index", {})
    out["index"] = idx_o if idx_o.get("built", "") >= idx_t.get("built", "") else idx_t
    airports = dict(theirs.get("airports", {}))
    for code, a in ours.get("airports", {}).items():
        if a.get("fetched", "") >= airports.get(code, {}).get("fetched", ""):
            airports[code] = a
    out["airports"] = airports
    return out


def main() -> None:
    ours, repo = Path(sys.argv[1]), Path(sys.argv[2])
    repo.mkdir(parents=True, exist_ok=True)
    for name in ("latest.json", "state.json"):
        if (ours / name).exists():
            (repo / name).write_text((ours / name).read_text())
    hist = merge_history(_load(repo / "history.json", {}), _load(ours / "history.json", {}))
    (repo / "history.json").write_text(json.dumps(hist))
    if (ours / "lounges.json").exists():
        lg = merge_lounges(_load(repo / "lounges.json", {}), _load(ours / "lounges.json", {}))
        (repo / "lounges.json").write_text(json.dumps(lg, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
