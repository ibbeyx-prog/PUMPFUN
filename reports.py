"""
Write one paper-trading report for every completed 24 hour window.
Reports are stored in DATA_DIR/reports.json and shown on the dashboard.
"""
import csv
import json
import os
import time
from datetime import datetime, timezone

import deskio

DATA = os.getenv("DATA_DIR", ".")
PATH = os.path.join(DATA, "reports.json")
DAY = 24 * 3600


def _parse(text):
    return deskio.parse_stamp(text)


def _fmt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")


def _load():
    if not os.path.exists(PATH):
        return {"origin": None, "reports": []}
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"origin": None, "reports": []}
    data.setdefault("origin", None)
    data.setdefault("reports", [])
    return data


def _save(data):
    os.makedirs(DATA, exist_ok=True)
    deskio.write_json(PATH, data)


def _rows():
    path = os.path.join(DATA, "trades.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _changes():
    path = os.path.join(DATA, "agent_tune.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("changes") or []
    except (OSError, json.JSONDecodeError):
        return []


def _symbol(rows, mint):
    for row in rows:
        if row.get("event") == "BUY" and row.get("mint") == mint:
            return (row.get("note") or "").split(" size")[0].strip() or mint[:4]
    return mint[:4]


def build(rows, changes, start, end):
    window = []
    for row in rows:
        ts = _parse(row.get("time"))
        if ts is not None and start <= ts < end:
            window.append(row)
    closed = [r for r in window if r.get("event") == "CLOSED"]
    pnls = [float(r["sol_pnl"]) for r in closed]
    wins = [p for p in pnls if p > 0]
    buys = sum(1 for r in window if r.get("event") == "BUY")
    skips = sum(1 for r in window if r.get("event") == "SKIP")
    fades = sum(1 for r in closed if float(r["sol_pnl"]) < 0 and float(r.get("x") or 1) < 1)
    best = max(closed, key=lambda r: float(r["sol_pnl"])) if closed else None
    worst = min(closed, key=lambda r: float(r["sol_pnl"])) if closed else None
    edits = []
    for change in changes:
        ts = _parse(change.get("time"))
        if ts is not None and start <= ts < end:
            edits.append(f"{change.get('what')} -> {change.get('to')}")
    pnl = round(sum(pnls), 4) if pnls else 0
    win_rate = (len(wins) / len(closed)) if closed else None
    if not closed and not buys:
        text = "No paper trades in this window."
    else:
        bits = [f"Closed {len(closed)}, pnl {pnl:+.3f} SOL"]
        if win_rate is not None:
            bits.append(f"won {len(wins)}/{len(closed)} ({win_rate:.0%})")
        if fades:
            bits.append(f"{fades} lost before 1x")
        if best:
            bits.append(f"best {_symbol(rows, best['mint'])} {float(best['sol_pnl']):+.3f}")
        if worst and worst is not best:
            bits.append(f"worst {_symbol(rows, worst['mint'])} {float(worst['sol_pnl']):+.3f}")
        if edits:
            bits.append("rule edits: " + ", ".join(edits[:4]))
        text = ". ".join(bits) + "."
    return {
        "start": _fmt(start),
        "end": _fmt(end),
        "closed": len(closed),
        "buys": buys,
        "skips": skips,
        "wins": len(wins),
        "win_rate": win_rate,
        "pnl": pnl,
        "best": None if not best else round(float(best["sol_pnl"]), 4),
        "worst": None if not worst else round(float(worst["sol_pnl"]), 4),
        "fades": fades,
        "edits": edits,
        "text": text,
    }


def roll():
    """Append a report for every 24h window that has fully elapsed."""
    data = _load()
    rows = _rows()
    if data["origin"] is None:
        times = [t for t in (_parse(r.get("time")) for r in rows) if t]
        data["origin"] = min(times) if times else time.time()
        _save(data)
    origin = data["origin"]
    now = time.time()
    changes = _changes()
    made = False
    while origin + (len(data["reports"]) + 1) * DAY <= now:
        start = origin + len(data["reports"]) * DAY
        data["reports"].append(build(rows, changes, start, start + DAY))
        made = True
    if made:
        _save(data)
    return data


def public():
    data = roll()
    origin = data["origin"] or time.time()
    nxt = origin + (len(data["reports"]) + 1) * DAY
    return {
        "reports": list(reversed(data["reports"][-30:])),
        "next_at": _fmt(nxt),
        "next_in_h": round(max(0, nxt - time.time()) / 3600, 1),
    }
