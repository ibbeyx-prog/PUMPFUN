"""
Paper-only rule edits. The agent may tighten or relax entry and early-cut
rules from its own closed trades. Every edit is appended to agent_tune.json.
"""
import csv
import json
import os
import time

import deskio

DATA = os.getenv("DATA_DIR", ".")
PATH = os.path.join(DATA, "agent_tune.json")

# None means "use config.json". Numbers are hard limits the agent cannot cross.
# Rule changes from closed trades, and the model review's settings, wait for this many closes.
# Tuning on 30 closes is mostly noise. Sizing still starts at 30.
REVIEW_CLOSES = 100

BOUNDS = {
    "min_sources": (1, 3),
    "entry_score": (55, 90),
    "max_change_5m": (40, 90),
    "max_new_entries_per_scan": (0, 1),
    "early_cut_x": (0.70, 0.90),
    "early_cut_min": (8, 20),
    "entry_cooldown_min": (180, 720),
    "entry_gap_min": (15, 90),
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
    deskio.write_json(PATH, data)


def value(name, default=None):
    stored = _load()["values"].get(name)
    return default if stored is None else stored


def _clip(name, new):
    lo, hi = BOUNDS[name]
    return type(lo)(min(hi, max(lo, new)))


def note(what, old, new, why):
    data = _load()
    data["changes"].insert(0, {
        "time": deskio.stamp(),
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
        "time": deskio.stamp(),
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
        "time": deskio.stamp(),
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


HOLD_ID = "research-hold-2026-10-26"
HOLD_DAYS = 14
HOLD_RULES = {
    "min_sources": 2,
    "entry_score": 80,
    "max_change_5m": 45,
    "early_cut_x": 0.70,
    "early_cut_min": 8,
    "entry_cooldown_min": 180,
    "entry_gap_min": 45,
}


def locked():
    return bool(_load().get("strategy_locked"))


def research_hold_until():
    try:
        return float(_load().get("research_hold_until") or 0)
    except (TypeError, ValueError):
        return 0.0


def research_hold_active():
    return research_hold_until() > time.time()


def may_edit(name):
    """During the research hold, only the Lab freeze switch may move."""
    if locked() and name != "max_new_entries_per_scan":
        return False
    if research_hold_active() and name != "max_new_entries_per_scan":
        return False
    return True


def ensure_research_hold():
    """Lock the high-bar set for 14 days and pause new paper entries until Lab freezes picks."""
    data = _load()
    if data.get("research_hold") == HOLD_ID:
        return False
    why = (
        "14-day research hold: lock score 80 / 2 sources / 0.70x cut / 45m gap. "
        "Pause new paper entries until Lab freezes picks. Scan still feeds Lab."
    )
    for name, new in HOLD_RULES.items():
        _set(data, name, new, why)
    _set(data, "max_new_entries_per_scan", 0, why)
    data["research_hold"] = HOLD_ID
    data["research_hold_until"] = time.time() + HOLD_DAYS * 86400
    data["changes"] = data["changes"][:100]
    _save(data)
    return True


def gate_entries_from_lab(has_frozen_picks):
    """While the hold is on, entries stay off until Lab freezes at least one pick."""
    if not research_hold_active():
        return False
    target = 1 if has_frozen_picks else 0
    data = _load()
    if data["values"].get("max_new_entries_per_scan") == target:
        return False
    why = (
        "Lab froze picks. One high-bar paper entry per scan again."
        if target else
        "Lab has no frozen picks. Pause new paper entries. Scan still feeds Lab."
    )
    if not _set(data, "max_new_entries_per_scan", target, why):
        return False
    data["changes"] = data["changes"][:100]
    _save(data)
    return True


def lock_strategy(why):
    data = _load()
    if data.get("strategy_locked"):
        return False
    data["strategy_locked"] = True
    data["changes"].insert(0, {
        "time": deskio.stamp(),
        "what": "strategy",
        "from": "grinding",
        "to": "stick",
        "why": why,
    })
    data["changes"] = data["changes"][:100]
    _save(data)
    return True


ENTRY_RULE_ID = "two-source"
ENTRY_RULE = {"min_sources": 2, "entry_score": 65, "max_change_5m": 60}


def ensure_entry_rule():
    """One-time switch to the 2-source paper entry. The 3-source rule never fired in 13,565 lab coins.
    The lab keeps the 3-source rule as the `strict` shadow books."""
    data = _load()
    if data.get("entry_rule") == ENTRY_RULE_ID or data.get("strategy_locked"):
        return False
    for name, new in ENTRY_RULE.items():
        _set(data, name, new, "Two-source paper entry: the 3-source rule took 0 trades in 13,565 lab coins.")
    data["entry_rule"] = ENTRY_RULE_ID
    data["changes"] = data["changes"][:100]
    _save(data)
    return True


def install_preset(values, why):
    """Replace the paper rules with one grind preset. A locked strategy is left alone."""
    if locked() or research_hold_active():
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
    if locked() or research_hold_active():
        return _load()
    rows = _closed_rows()
    data = _load()
    if len(rows) < REVIEW_CLOSES or len(rows) == data.get("reviewed_closes"):
        return data
    buckets, _stops = _bucket(rows)
    n = len(rows)
    wr = _wr([p for xs in buckets.values() for p in xs])
    fades = sum(1 for r in rows if float(r["sol_pnl"]) < 0 and float(r.get("x") or 1) < 1)
    recent = rows[-15:]
    recent_wr = _wr([float(r["sol_pnl"]) for r in recent])
    changed = False
    paused = data["values"].get("max_new_entries_per_scan") == 0

    # Resume before tightening: a cold book that starts winning again should trade again.
    if paused and recent_wr is not None and recent_wr >= 0.25 and len(recent) >= 10:
        changed |= _set(data, "max_new_entries_per_scan", 1,
                        f"Last {len(recent)} closes won {recent_wr:.0%}. Open one paper entry per scan again.")
        paused = False

    two = buckets.get(2) or []
    two_pnl = sum(two) if two else 0.0
    # Only demand a third source when two-source closes both lose often and lose money.
    if (len(two) >= 3 and _wr(two) is not None and _wr(two) < 0.35 and two_pnl <= 0
            and data["values"].get("min_sources", 1) < 3):
        changed |= _set(data, "min_sources", 3,
                        f"2-source closes won {_wr(two):.0%} of {len(two)} and lost {two_pnl:+.3f} SOL. Require 3 sources.")
    elif (buckets.get(1) and len(buckets[1]) >= 3 and _wr(buckets[1]) < 0.4
          and data["values"].get("min_sources", 1) < 2):
        changed |= _set(data, "min_sources", 2,
                        f"1-source closes won {_wr(buckets[1]):.0%} of {len(buckets[1])}.")

    if fades / n >= 0.45:
        cut = data["values"].get("early_cut_x")
        if cut is None:
            changed |= _set(data, "early_cut_x", 0.80,
                            f"{fades} of {n} closes lost before 1x. Cut weak trades before the full stop.")
            changed |= _set(data, "early_cut_min", 10, "Wait 10 minutes before that early cut.")
        elif float(cut) > 0.75 and fades / n >= 0.55:
            changed |= _set(data, "early_cut_x", 0.75,
                            f"{fades} of {n} closes still fade under 1x. Cut at 0.75x after 8 minutes.")
            changed |= _set(data, "early_cut_min", 8, "Wait 8 minutes before that harder early cut.")
    elif wr is not None and wr >= 0.5 and fades / n < 0.3:
        changed |= _clear(data, "early_cut_x", "Stops are no longer the usual exit.")
        changed |= _clear(data, "early_cut_min", "Early cut turned off with the rule above.")

    if wr is not None and wr < 0.25:
        score = data["values"].get("entry_score", 60)
        target = 70 if score is None or score < 70 else (85 if score < 85 and wr < 0.18 else None)
        if target is not None and (score is None or score < target):
            changed |= _set(data, "entry_score", target,
                            f"Only {wr:.0%} of {n} closes won. Demand a score of {target} or more.")

    three = buckets.get(3) or []
    import eye
    hostile = eye.tool_rules().get("hostile")
    if (not hostile and wr is not None and wr >= 0.55 and len(three) >= 3 and _wr(three) >= 0.5
            and data["values"].get("min_sources", 1) > 2):
        changed |= _set(data, "min_sources", 2,
                        "Recent closes are paying again. Allow a 2-source entry.")

    # When the book is already tight and still cold, stop opening new paper trades.
    tight = (
        data["values"].get("min_sources", 1) >= 3
        and data["values"].get("entry_score", 60) >= 80
        and data["values"].get("early_cut_x") is not None
    )
    if (not paused and tight and wr is not None and wr < 0.18
            and (recent_wr is None or recent_wr < 0.15)):
        changed |= _set(data, "max_new_entries_per_scan", 0,
                        f"{wr:.0%} of {n} closes won after a tight book. Pause new paper entries until the last 15 win 25%.")

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
