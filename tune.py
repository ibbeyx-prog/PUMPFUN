"""
Paper-only rule edits. The agent may tighten or relax entry and early-cut
rules from its own closed trades. Every edit is appended to agent_tune.json.
"""
import csv
import json
import os
import time

DATA = os.getenv("DATA_DIR", ".")
PATH = os.path.join(DATA, "agent_tune.json")

# None means "use config.json". Numbers are hard limits the agent cannot cross.
BOUNDS = {
    "min_sources": (1, 3),
    "entry_score": (55, 80),
    "max_change_5m": (40, 90),
    "max_new_entries_per_scan": (0, 1),
    "early_cut_x": (0.70, 0.90),
    "early_cut_min": (8, 20),
}


def _load():
    if not os.path.exists(PATH):
        return {"values": {}, "reviewed_closes": 0, "changes": []}
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"values": {}, "reviewed_closes": 0, "changes": []}
    data.setdefault("values", {})
    data.setdefault("changes", [])
    data.setdefault("reviewed_closes", 0)
    return data


def _save(data):
    os.makedirs(DATA, exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def value(name, default=None):
    stored = _load()["values"].get(name)
    return default if stored is None else stored


def _clip(name, new):
    lo, hi = BOUNDS[name]
    return type(lo)(min(hi, max(lo, new)))


def note(what, old, new, why):
    data = _load()
    data["changes"].insert(0, {
        "time": time.strftime("%F %T"),
        "what": what,
        "from": "" if old is None else str(old),
        "to": "" if new is None else str(new),
        "why": why,
    })
    data["changes"] = data["changes"][:100]
    _save(data)


def _set(data, name, new, why):
    old = data["values"].get(name)
    new = _clip(name, new)
    if old == new:
        return False
    data["values"][name] = new
    data["changes"].insert(0, {
        "time": time.strftime("%F %T"),
        "what": name,
        "from": "" if old is None else str(old),
        "to": str(new),
        "why": why,
    })
    return True


def _clear(data, name, why):
    if name not in data["values"]:
        return False
    old = data["values"].pop(name)
    data["changes"].insert(0, {
        "time": time.strftime("%F %T"),
        "what": name,
        "from": str(old),
        "to": "off",
        "why": why,
    })
    return True


def _closed_rows():
    path = os.path.join(DATA, "trades.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    last = -1
    for i, row in enumerate(rows):
        if row.get("event") == "RESET":
            last = i
    return [row for row in rows[last + 1:] if row.get("event") == "CLOSED"]


def _bucket(rows):
    out = {}
    stops = 0
    for r in rows:
        n = len([s for s in (r.get("wallet") or "").split("+") if s]) or 1
        out.setdefault(n, []).append(float(r["sol_pnl"]))
        if "stop-loss" in (r.get("note") or ""):
            stops += 1
    return out, stops


def _wr(xs):
    return sum(1 for x in xs if x > 0) / len(xs) if xs else None


def locked():
    return bool(_load().get("strategy_locked"))


def lock_strategy(why):
    data = _load()
    if data.get("strategy_locked"):
        return False
    data["strategy_locked"] = True
    data["changes"].insert(0, {
        "time": time.strftime("%F %T"),
        "what": "strategy",
        "from": "grinding",
        "to": "stick",
        "why": why,
    })
    data["changes"] = data["changes"][:100]
    _save(data)
    return True


def install_preset(values, why):
    """Replace the paper rules with one grind preset. A locked strategy is left alone."""
    if locked():
        return False
    data = _load()
    for name, new in values.items():
        if name not in BOUNDS:
            continue
        _set(data, name, new, why)
    data["reviewed_closes"] = 0
    data["changes"] = data["changes"][:100]
    _save(data)
    return True


def review():
    """Move the paper rules toward whatever the closed trades support. One pass per new close."""
    if locked():
        return _load()
    rows = _closed_rows()
    data = _load()
    if len(rows) < 5 or len(rows) == data.get("reviewed_closes"):
        return data
    buckets, _stops = _bucket(rows)
    n = len(rows)
    wr = _wr([p for xs in buckets.values() for p in xs])
    fades = sum(1 for r in rows if float(r["sol_pnl"]) < 0 and float(r.get("x") or 1) < 1)
    changed = False

    two = buckets.get(2) or []
    if len(two) >= 3 and _wr(two) < 0.35 and data["values"].get("min_sources", 1) < 3:
        changed |= _set(data, "min_sources", 3,
                        f"2-source closes won {_wr(two):.0%} of {len(two)}. Require 3 sources.")
    elif (buckets.get(1) and len(buckets[1]) >= 3 and _wr(buckets[1]) < 0.4
          and data["values"].get("min_sources", 1) < 2):
        changed |= _set(data, "min_sources", 2,
                        f"1-source closes won {_wr(buckets[1]):.0%} of {len(buckets[1])}.")

    if fades / n >= 0.45 and "early_cut_x" not in data["values"]:
        changed |= _set(data, "early_cut_x", 0.80,
                        f"{fades} of {n} closes lost before 1x. Cut weak trades before the full stop.")
        changed |= _set(data, "early_cut_min", 10, "Wait 10 minutes before that early cut.")
    elif wr is not None and wr >= 0.5 and fades / n < 0.3:
        changed |= _clear(data, "early_cut_x", "Stops are no longer the usual exit.")
        changed |= _clear(data, "early_cut_min", "Early cut turned off with the rule above.")

    if wr is not None and wr < 0.25 and data["values"].get("entry_score", 60) < 70:
        changed |= _set(data, "entry_score", 70,
                        f"Only {wr:.0%} of {n} closes won. Demand a higher entry score.")

    three = buckets.get(3) or []
    if (wr is not None and wr >= 0.55 and len(three) >= 3 and _wr(three) >= 0.5
            and data["values"].get("min_sources", 1) > 2):
        changed |= _set(data, "min_sources", 2,
                        "Recent closes are paying again. Allow a 2-source entry.")

    data["reviewed_closes"] = n
    data["changes"] = data["changes"][:100]
    if changed or data.get("reviewed_closes") != _load().get("reviewed_closes"):
        _save(data)
    return data


def public():
    data = _load()
    return {
        "values": data["values"],
        "reviewed_closes": data["reviewed_closes"],
        "changes": data["changes"][:40],
    }
