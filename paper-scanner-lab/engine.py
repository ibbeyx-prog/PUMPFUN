"""Replay rules on recorded scans. No network, no desk files, no orders."""
import math
import random
from dataclasses import dataclass

FEE = 0.01
FLAT_USD = 0.20
SLIP_BASE = 0.03
SLIP_IMPACT = 2.0
SLIP_CAP = 0.80
ENTRY_DELAY_S = 45
TWO_X = 2.0
STOP_X = 0.65
PULLBACK = 0.10
PULLBACK_WAIT_S = 15 * 60
HOLD_S = 3 * 60
# The desk gives up after about 70 seconds. The lab polls once a minute, so it allows two minutes
# past the 45-second delay. A coin first priced later than that had no timely fill and is not traded.
ENTRY_WINDOW_S = 120
TRACK_S = 4 * 3600
VANISH_LEFT = 0.10
SIZE_USD = 5.0
MIN_CHANGE = 5.0
CONFIRM = ("gmgn", "dexscreener", "birdeye")
# The desk's hard skips. "rugcheck 12" on a clean coin is a bonus note, not a skip, so the
# RugCheck and Bubblemaps blocks are matched by their "rugcheck:" and "bubblemap:" prefixes.
HARD_WORDS = (
    "mcap outside", "thin liquidity", "no liquidity", "rug risk", "bundled", "wash",
    "too new", "too old", "rugcheck:", "bubblemap:", "liquidity under 8%", "younger than 5",
)


@dataclass(frozen=True)
class Book:
    id: str
    name: str
    min_sources: int
    entry_score: float
    max_change_5m: float
    early_cut_x: float | None
    early_cut_min: float | None
    stop: float
    time_stop_min: float
    ladder: tuple
    runner: tuple | None = None
    confirm: bool = True
    need_move: bool = True


def _ladder():
    return ((2.0, 0.40), (3.5, 0.30), (5.0, 1.0))


# id, name, min sources, entry score, 5-minute cap, needs a confirming feed, needs a 5-minute move in band
ENTRY_RULES = (
    ("strict", "Strict", 3, 70, 45, True, True),
    ("desk", "Desk", 2, 65, 60, True, True),
    ("loose", "Loose", 2, 55, 90, True, True),
    ("looser", "Looser", 1, -1e9, 90, True, True),
    ("filters", "Filters only", 0, -1e9, 1e9, False, False),
)
# id, name, early cut x, early cut minutes, stop, time stop minutes, ladder, runner
EXITS = (
    ("ladder", "ladder", 0.80, 10, 0.35, 90, _ladder(), None),
    ("cut", "cut fast", 0.85, 8, 0.35, 60, _ladder(), None),
    ("runner", "runner", 0.80, 10, 0.35, 90, (), (2.0, 0.5, 0.30)),
    ("wide", "wide stop", None, None, 0.50, 180, _ladder(), None),
)
REFERENCE_ID = "filters-ladder"


def _books():
    out = []
    for eid, ename, sources, score, chase, confirm, need_move in ENTRY_RULES:
        for xid, xname, cut_x, cut_min, stop, time_stop, ladder, runner in EXITS:
            out.append(Book(
                f"{eid}-{xid}", f"{ename} / {xname}", sources, score, chase,
                cut_x, cut_min, stop, time_stop, ladder, runner, confirm, need_move,
            ))
    return tuple(out)


BOOKS = _books()


def slippage(size_usd, liq_usd):
    """Same rule as the desk: 3% plus twice size over pool liquidity, capped at 80%. Unknown liquidity is 3%."""
    liq = float(liq_usd or 0)
    if liq <= 0:
        return SLIP_BASE
    return min(SLIP_CAP, SLIP_BASE + SLIP_IMPACT * float(size_usd) / liq)


PARTS = ("move", "stop_gap", "slippage", "fee", "flat")


def round_trip_cost_usd(trade_usd, liq_usd=0):
    """Same as copytrader.round_trip_cost_usd: both sides pay 1% plus $0.20, and slippage."""
    usd = float(trade_usd or 0)
    return round(2 * (FEE * usd + FLAT_USD) + 2 * slippage(usd, liq_usd) * usd, 2)


def fill_price(entry_px, ticket_usd, liq_usd):
    """The desk's paper fill: the quote plus slippage on the whole ticket."""
    return entry_px * (1 + slippage(ticket_usd, liq_usd))


def entry_parts(ticket_usd):
    """Charged once when the desk opens: 1% of the ticket and $0.20."""
    return {"move": 0.0, "stop_gap": 0.0, "slippage": 0.0, "fee": -FEE * ticket_usd, "flat": -FLAT_USD}


def piece_parts(entry_px, exit_px, ticket_usd, frac, liq_usd):
    """One sale of `frac` of the position, with the desk's sell math, split into its parts.

    Entry slippage is the gap between the quote and the fill. Exit slippage is charged on the
    current value. The parts sum to the sale's PnL. The entry fee is in entry_parts().
    """
    base = ticket_usd * frac
    if entry_px <= 0 or exit_px <= 0:
        return {"move": -0.90 * base, "stop_gap": 0.0, "slippage": 0.0, "fee": 0.0, "flat": -FLAT_USD}
    fill = fill_price(entry_px, ticket_usd, liq_usd)
    raw_x = exit_px / entry_px
    x = exit_px / fill
    gross = base * x
    exit_slip = slippage(gross, liq_usd)
    return {
        "move": base * (raw_x - 1),
        "stop_gap": 0.0,
        "slippage": base * (x - raw_x) - gross * exit_slip,
        "fee": -gross * (1 - exit_slip) * FEE,
        "flat": -FLAT_USD,
    }


def piece(entry_px, exit_px, size_usd, liq_usd):
    """Selling the whole position. The entry's 1% and $0.20 are charged once by the caller."""
    return sum(piece_parts(entry_px, exit_px, size_usd, 1.0, liq_usd).values())


def round_trip(entry_px, exit_px, size_usd, liq_usd):
    """A full buy and sell with the desk's fees: 1% and $0.20 each side, and slippage."""
    return piece(entry_px, exit_px, size_usd, liq_usd) + sum(entry_parts(size_usd).values())


def vanished_pnl(size_usd=SIZE_USD):
    """A token that disappears is treated as a sale at 10% of entry, then fees."""
    return round_trip(1.0, VANISH_LEFT, size_usd, liq_usd=10**9)


def hard_skip(note):
    text = (note or "").lower()
    return any(word in text for word in HARD_WORDS)


def would_enter(book, snap):
    """Replay one book's entry rule on a recorded snapshot."""
    if hard_skip(snap.get("note")):
        return False
    sources = list(snap.get("sources") or [])
    if len(sources) < book.min_sources:
        return False
    if book.confirm and not any(name in sources for name in CONFIRM):
        return False
    score = snap.get("score")
    if book.entry_score > -1e8 and (score is None or float(score) < book.entry_score):
        return False
    change = snap.get("change_5m")
    if book.need_move and (change is None or not (MIN_CHANGE <= float(change) <= book.max_change_5m)):
        return False
    age = snap.get("age_min")
    if age is not None and float(age) < 5:
        return False
    mcap = snap.get("mcap")
    if mcap is not None and not (500000 <= float(mcap) <= 2000000):
        return False
    liq = snap.get("liq")
    if liq is not None and float(liq) < 8000:
        return False
    return True


def _price_at(path, t):
    chosen = None
    for at, price in path:
        if at >= t and price and price > 0:
            return at, price
        if price and price > 0:
            chosen = (at, price)
    return chosen


ENTRIES = ("delay", "pullback", "hold")


def entry_point(path, start, mode="delay"):
    """When a book would buy. delay: first price 45s after the signal. pullback: first price 10% under
    the first quote within 15 minutes. hold: the price 3 minutes after the first quote, only if it is
    still at or above it. None means no buy."""
    points = [(at, float(px)) for at, px in path if px and px > 0 and at >= start]
    latest = start + ENTRY_DELAY_S + ENTRY_WINDOW_S
    if mode == "delay":
        point = next(((at, px) for at, px in points if at >= start + ENTRY_DELAY_S), None)
        return point if point and point[0] <= latest else None
    if not points or points[0][0] > latest:
        return None
    t0, p0 = points[0]
    if mode == "pullback":
        for at, px in points:
            if at > t0 + PULLBACK_WAIT_S:
                return None
            if px <= p0 * (1 - PULLBACK):
                return at, px
        return None
    if mode == "hold":
        for at, px in points:
            if at >= t0 + HOLD_S:
                return (at, px) if px >= p0 else None
        return None
    raise ValueError(mode)


def _vanished_trade(size_usd, at=0.0):
    parts = entry_parts(size_usd)
    for key, value in piece_parts(1.0, VANISH_LEFT, size_usd, 1.0, 0).items():
        parts[key] += value
    pnl = sum(parts.values())
    return {"pnl": pnl, "reason": "vanished", "multiple": VANISH_LEFT, "win": False,
            "parts": parts, "peak": 1.0, "close_x": VANISH_LEFT, "entry_at": at, "exit_at": at}


def simulate(book, snap, path, size_usd=SIZE_USD, entry="delay"):
    """Walk one 4-hour path. Returns None when there is no timely entry price, as the desk would skip."""
    start = float(snap["started_at"])
    end = start + TRACK_S
    point = entry_point(path, start, entry)
    if point is None:
        return None
    entry_at, entry_px = point
    liq = snap.get("liq")
    # Like the desk, ladder, stop, and cut decisions read the multiple against the slipped fill.
    fill = fill_price(entry_px, size_usd, liq)
    left = 1.0
    tier = 0
    runner_peak = 1.0
    parts = entry_parts(size_usd)
    stop_seen = False
    cut_seen = False
    last_x = 1.0
    peak = 1.0
    close_x = 0.0
    exit_at = entry_at
    reason = "mark"
    points = [(at, px) for at, px in path if entry_at <= at <= end and px and px > 0]
    if not points:
        return _vanished_trade(size_usd, entry_at)
    vanished = (end - points[-1][0]) > 15 * 60

    def sell(frac, px, why, at):
        nonlocal left, reason, close_x, exit_at
        frac = min(frac, left)
        if frac <= 0:
            return
        got = piece_parts(entry_px, px, size_usd, frac, liq)
        x = px / fill
        if why == "stop":
            gap = size_usd * frac * (x - (1 - book.stop))
            got["move"] -= gap
            got["stop_gap"] = gap
        for key, value in got.items():
            parts[key] += value
        close_x += frac * x
        left -= frac
        reason = why
        exit_at = at

    for at, px in points:
        last_x = px / fill
        peak = max(peak, px / entry_px)
        age_min = (at - entry_at) / 60
        if last_x <= 1 - book.stop:
            if stop_seen:
                sell(left, px, "stop", at)
                break
            stop_seen = True
        else:
            stop_seen = False
        if book.early_cut_x and age_min >= book.early_cut_min and last_x <= book.early_cut_x and last_x < 2:
            if cut_seen:
                sell(left, px, "early-cut", at)
                break
            cut_seen = True
        else:
            cut_seen = False
        if age_min >= book.time_stop_min and last_x < 2:
            sell(left, px, "time-stop", at)
            break
        if book.runner:
            first_x, first_frac, trail = book.runner
            if tier == 0 and last_x >= first_x:
                sell(first_frac, px, f"runner {first_x:g}x", at)
                tier = 1
                runner_peak = last_x
            elif tier >= 1:
                runner_peak = max(runner_peak, last_x)
                if last_x <= runner_peak * (1 - trail):
                    sell(left, px, "trail", at)
                    break
            if left <= 1e-9:
                break
            continue
        while tier < len(book.ladder) and last_x >= book.ladder[tier][0] and left > 0:
            multiple, frac = book.ladder[tier]
            tier += 1
            take = left if frac >= 1 else frac
            sell(take, px, f"ladder {multiple:g}x", at)
            if left <= 1e-9:
                break
        if left <= 1e-9:
            break
    if left > 1e-9:
        if vanished:
            sell(left, entry_px * VANISH_LEFT, "vanished", points[-1][0])
        else:
            sell(left, points[-1][1], "window", points[-1][0])
    pnl = sum(parts.values())
    return {"pnl": pnl, "reason": reason, "multiple": last_x, "win": pnl > 0,
            "parts": parts, "peak": peak, "close_x": close_x, "entry_at": entry_at, "exit_at": exit_at}


def label_move(path, start, up=TWO_X, down=STOP_X):
    """True if the price reached `up` times the 45s entry quote before `down` times it, before costs.
    None without a timely entry."""
    point = entry_point(path, start, "delay")
    if point is None:
        return None
    entry_at, entry_px = point
    for at, px in path:
        if at < entry_at or not px or px <= 0 or at > start + TRACK_S:
            continue
        x = px / entry_px
        if x >= up:
            return True
        if x <= down:
            return False
    return False


def label_2x(path, start):
    """2x before 0.65x."""
    return label_move(path, start, TWO_X, STOP_X)


def label_15(path, start):
    """1.5x before a 35% drop. More positives than 2x, for the learned score."""
    return label_move(path, start, 1.5, 0.65)


def bootstrap_ci(pnls, draws=1000, seed=0):
    if not pnls:
        return None
    rng = random.Random(seed)
    n = len(pnls)
    means = []
    for _ in range(draws):
        means.append(sum(pnls[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(0.025 * (draws - 1))]
    hi = means[min(len(means) - 1, int(0.975 * (draws - 1)))]
    return {"low": lo, "high": hi, "mean": sum(pnls) / n}


def verdict(n, ci):
    if n < 30 or not ci:
        return "too few trades to tell"
    if ci["low"] > 0:
        return "beats zero"
    if ci["high"] < 0:
        return "loses to zero"
    return "not distinguishable from luck"


def sample_label(n):
    if n >= 300:
        return "trustworthy"
    if n >= 100:
        return "meaningful"
    return "early"


def random_percentile(strategy_total, pool, n_trades, draws=400, seed=0):
    """Share of random same-size samples whose total is below this strategy."""
    if n_trades <= 0 or len(pool) < n_trades:
        return None
    rng = random.Random(seed)
    below = 0
    for _ in range(draws):
        pick = [pool[rng.randrange(len(pool))] for _ in range(n_trades)]
        if sum(pick) < strategy_total:
            below += 1
    return 100.0 * below / draws


def skip_reason(note, decision):
    if decision != "skip":
        return ""
    text = note or "unspecified"
    for part in text.split(","):
        part = part.strip()
        if any(word in part.lower() for word in HARD_WORDS) or part.lower().startswith("skill") or part.lower().startswith("rugcheck") or part.lower().startswith("bubblemap") or "source" in part.lower() or "chas" in part.lower():
            return part[:80]
    return text.split(",")[0].strip()[:80] or "unspecified"


def bucket_score(score):
    if score is None:
        return "unknown"
    score = float(score)
    if score < 60:
        return "under 60"
    if score < 70:
        return "60–69"
    if score < 80:
        return "70–79"
    return "80+"


def _group(rows, key):
    groups = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    out = []
    for name, items in groups.items():
        values = [r["forward"] for r in items]
        labeled = [r["hit2x"] for r in items if r.get("hit2x") is not None]
        out.append({
            "name": name,
            "n": len(values),
            "mean": sum(values) / len(values),
            "win_rate": sum(1 for v in values if v > 0) / len(values),
            "rate_2x": (sum(1 for v in labeled if v) / len(labeled)) if labeled else None,
        })
    out.sort(key=lambda item: (-item["n"], item["name"]))
    return out


def outcome_tables(episodes):
    """Forward return from the delayed entry to the 4-hour mark, and the share that hit 2x before 0.65x."""
    rows = [ep for ep in episodes if ep.get("forward") is not None]
    return {
        "by_decision": _group(rows, lambda r: r.get("decision") or "unknown"),
        "by_score": _group(rows, lambda r: bucket_score(r.get("score"))),
        "by_sources": _group(rows, lambda r: str(min(3, len(r.get("sources") or []))) + ("+" if len(r.get("sources") or []) >= 3 else "")),
        "by_skip": _group(
            [r for r in rows if r.get("decision") == "skip"],
            lambda r: skip_reason(r.get("note"), "skip"),
        ),
    }


TICKETS = (5.5, 8.0, 12.0)
LADDER_ID = "desk-ladder"
EDGE_MIN_N = 100
LATE_COPY = "copy arrives late"


def book_by_id(book_id):
    return next(book for book in BOOKS if book.id == book_id)


def _exit_key(book):
    return (book.early_cut_x, book.early_cut_min, book.stop, book.time_stop_min, book.ladder, book.runner)


class Replay:
    """Simulations shared across books. Books with the same exits get the same forced trade per coin."""

    def __init__(self, episodes):
        self.ready = [ep for ep in episodes if ep.get("path")]
        self._memo = {}

    def trade(self, book, i, size_usd, entry="delay"):
        key = (_exit_key(book), i, size_usd, entry)
        if key not in self._memo:
            ep = self.ready[i]
            self._memo[key] = simulate(book, ep, ep["path"], size_usd, entry)
        return self._memo[key]

    def run(self, book, size_usd, taken_only=True, entry="delay", snap_fn=None):
        taken, pool = [], []
        for i, ep in enumerate(self.ready):
            trade = self.trade(book, i, size_usd, entry)
            if trade is None:
                continue
            pool.append(trade["pnl"])
            snap = snap_fn(ep) if snap_fn else ep
            if not taken_only or would_enter(book, snap):
                taken.append(trade)
        return taken, pool


def _median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def breakdown(trades):
    """Mean dollars per trade from price move, stop gaps, slippage, the 1% fee, and the $0.20 per transaction."""
    if not trades:
        return None
    n = len(trades)
    out = {key: sum(t["parts"][key] for t in trades) / n for key in PARTS}
    out["before_costs"] = out["move"] + out["stop_gap"]
    out["costs"] = out["slippage"] + out["fee"] + out["flat"]
    out["net"] = sum(t["pnl"] for t in trades) / n
    out["peak"] = _median([t["peak"] for t in trades])
    out["close_x"] = _median([t["close_x"] for t in trades])
    out["gave_back"] = sum(1 for t in trades if t["peak"] >= 1.5 and t["close_x"] < 1.2) / n
    out["n"] = n
    return out


def _row(book_id, name, taken, pool, size_usd):
    pnls = [t["pnl"] for t in taken]
    seed = sum(ord(ch) for ch in book_id)
    ci = bootstrap_ci(pnls, seed=seed) if pnls else None
    total = sum(pnls)
    return {
        "id": book_id,
        "name": name,
        "size_usd": size_usd,
        "n": len(pnls),
        "total": total if pnls else None,
        "mean": (total / len(pnls)) if pnls else None,
        "win_rate": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
        "ci": ci,
        "verdict": verdict(len(pnls), ci) if ci else "too few trades to tell",
        "random_percentile": random_percentile(total, pool, len(pnls), seed=seed) if pnls else None,
        "parts": breakdown(taken),
    }


def paired_vs_reference(replay, book, size_usd=SIZE_USD, draws=200, seed=7):
    """Dollars per signal against the filters-only ladder, on the signals that book would take.

    A signal the book skips counts as 0 for the book, so trading less is allowed to win.
    """
    ref = book_by_id(REFERENCE_ID)
    diffs = []
    for i, ep in enumerate(replay.ready):
        if not would_enter(ref, ep):
            continue
        r = replay.trade(ref, i, size_usd)
        if r is None:
            continue
        b = replay.trade(book, i, size_usd) if would_enter(book, ep) else None
        diffs.append((b["pnl"] if b else 0.0) - r["pnl"])
    n = len(diffs)
    if not n:
        return {"signals": 0, "mean": None, "low": None, "high": None}
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(draws))
    return {
        "signals": n,
        "mean": sum(diffs) / n,
        "low": means[int(0.025 * (draws - 1))],
        "high": means[int(0.975 * (draws - 1))],
    }


def run_books(replay, size_usd=SIZE_USD, paired=True):
    """Twenty research books on the same recorded signals. They ignore the desk's cooldown,
    one-entry-per-scan, and open-position limits, so they collect more trades than the desk."""
    results = []
    for book in BOOKS:
        taken, pool = replay.run(book, size_usd)
        row = _row(book.id, book.name, taken, pool, size_usd)
        row["paired"] = paired_vs_reference(replay, book, size_usd) if paired else None
        results.append(row)
    results.sort(key=lambda row: (row["total"] is not None, row["total"] or 0), reverse=True)
    return results


REAL_DESK_ID = "desk-ladder-real"
MAX_OPEN = 5


def run_real_desk(replay, size_usd=SIZE_USD, max_open=MAX_OPEN):
    """The desk's own book with its limits: one entry per scan and at most five open. The 180-minute
    cooldown holds because a coin gets one 4-hour episode at a time. This row feeds the live gate."""
    book = book_by_id(LADDER_ID)
    signals = sorted(
        (ep["started_at"], i) for i, ep in enumerate(replay.ready) if would_enter(book, ep)
    )
    taken = []
    open_until = []
    last_scan = None
    for start, i in signals:
        if start == last_scan:
            continue
        open_until = [t for t in open_until if t > start]
        if len(open_until) >= max_open:
            continue
        trade = replay.trade(book, i, size_usd)
        if trade is None:
            continue
        taken.append(trade)
        open_until.append(trade["exit_at"])
        last_scan = start
    _, pool = replay.run(book, size_usd, taken_only=False)
    return _row(REAL_DESK_ID, "Desk / ladder, real limits", taken, pool, size_usd)


def pick_leaders(rows, k=3, min_n=30):
    """Top books by paired difference against the filters-only ladder, with enough trades."""
    ok = [
        r for r in rows
        if r["id"] != REFERENCE_ID and r["n"] >= min_n and (r.get("paired") or {}).get("mean") is not None
    ]
    ok.sort(key=lambda r: -r["paired"]["mean"])
    return [r["id"] for r in ok[:k]]


def ticket_books(replay, rows):
    """The three best entry rules on the ladder exit, at $5.50, $8, and $12."""
    ranked = sorted(
        (r for r in rows if r["id"].endswith("-ladder") and r["id"] != REFERENCE_ID and r["n"] >= 30),
        key=lambda r: -(r["mean"] or 0),
    )
    entries = [r["id"][: -len("-ladder")] for r in ranked[:3]]
    for fallback in ("desk", "loose", "looser"):
        if len(entries) < 3 and fallback not in entries:
            entries.append(fallback)
    out = []
    for entry in entries:
        book = book_by_id(f"{entry}-ladder")
        for size in TICKETS:
            taken, pool = replay.run(book, size)
            out.append(_row(f"{entry}-ladder-{size:g}", f"{book.name} ${size:g}", taken, pool, size))
    return out


def baselines(replay, size_usd=5.5):
    """Hold SOL does not trade. Buy-every-name uses the ladder exits on every coin with a timely price."""
    desk = book_by_id(LADDER_ID)
    taken, pool = replay.run(desk, size_usd, taken_only=False)
    hold = {
        "id": "hold-sol", "name": "Hold SOL", "size_usd": 0, "n": len(taken),
        "total": 0, "mean": 0, "win_rate": None, "ci": None,
        "verdict": "baseline", "random_percentile": None, "parts": None,
    }
    every = _row("buy-every-name", "Buy every tracked name", taken, pool, size_usd)
    every["verdict"] = "baseline"
    return [hold, every]


def _summary(trades, size_usd):
    pnls = [t["pnl"] for t in trades]
    n = len(pnls)
    return {
        "n": n,
        "total": sum(pnls) if n else None,
        "mean": (sum(pnls) / n) if n else None,
        "per_dollar": (sum(pnls) / n / size_usd) if n else None,
        "win_rate": (sum(1 for p in pnls if p > 0) / n) if n else None,
    }


def entry_timing(replay, size_usd=5.5):
    """Buy 45s after the signal, on a 10% pullback within 15 minutes, or only if the price holds for 3 minutes."""
    out = []
    groups = (
        ("every tracked coin", book_by_id(LADDER_ID), False),
        ("loose entry rule", book_by_id("loose-ladder"), True),
    )
    for group, book, only in groups:
        for mode in ENTRIES:
            taken, _ = replay.run(book, size_usd, only, mode)
            out.append({"group": group, "entry": mode, **_summary(taken, size_usd)})
    return out


def regime(replay, now, size_usd=5.5, window=86400):
    """Share of tracked coins that hit 2x before 0.65x over the 24 hours before each signal.

    Only coins whose 4-hour window has closed are counted, so a rate never uses the future.
    The lab suggests a pause only when the bottom quarter of rates also lost more than the rest.
    """
    import bisect
    labeled = sorted(
        (ep["started_at"], 1 if ep["hit2x"] else 0)
        for ep in replay.ready if ep.get("hit2x") is not None
    )
    times = [t for t, _ in labeled]
    wins = [0]
    for _, hit in labeled:
        wins.append(wins[-1] + hit)

    def rate(t):
        hi = bisect.bisect_left(times, t - TRACK_S)
        lo = bisect.bisect_left(times, t - TRACK_S - window)
        n = hi - lo
        return ((wins[hi] - wins[lo]) / n if n >= 30 else None), n

    current, n_now = rate(now)
    ladder = book_by_id(LADDER_ID)
    pairs = []
    for i, ep in enumerate(replay.ready):
        r, _ = rate(ep["started_at"])
        if r is None:
            continue
        trade = replay.trade(ladder, i, size_usd)
        if trade is not None:
            pairs.append((r, trade))
    span = (times[-1] - times[0]) / 86400 if times else 0.0
    out = {
        "rate_24h": current, "n_24h": n_now, "threshold": None,
        "cold": None, "warm": None, "pause": False,
        "why": "needs 3 days and 200 coins with a prior 24-hour rate",
    }
    if len(pairs) < 200 or span < 3:
        return out
    rates = sorted(r for r, _ in pairs)
    threshold = rates[len(rates) // 4]
    cold = _summary([t for r, t in pairs if r < threshold], size_usd)
    warm = _summary([t for r, t in pairs if r >= threshold], size_usd)
    helps = cold["n"] >= 30 and warm["n"] >= 30 and cold["mean"] < warm["mean"]
    pause = bool(helps and current is not None and current < threshold)
    out.update(threshold=threshold, cold=cold, warm=warm, pause=pause)
    if not helps:
        out["why"] = "cold markets did not lose more than warm ones, so the rate is not used"
    elif pause:
        out["why"] = f"2x share {current:.1%} is under the bottom-quarter line {threshold:.1%}"
    else:
        out["why"] = "the market is not in its bottom quarter"
    return out


def score_edges(replay, size_usd=5.5):
    """Per score bucket, ladder trades on every coin: price move before costs against the costs."""
    ladder = book_by_id(LADDER_ID)
    groups = {}
    for i, ep in enumerate(replay.ready):
        trade = replay.trade(ladder, i, size_usd)
        if trade is not None:
            groups.setdefault(bucket_score(ep.get("score")), []).append(trade)
    out = []
    for name in ("under 60", "60–69", "70–79", "80+", "unknown"):
        parts = breakdown(groups.get(name) or [])
        if not parts:
            continue
        out.append({
            "bucket": name,
            "n": parts["n"],
            "before_costs": parts["before_costs"],
            "costs": parts["costs"],
            "net": parts["net"],
            "parts": parts,
            "pays": parts["net"] > 0 if parts["n"] >= EDGE_MIN_N else None,
        })
    return out


def rule_tests(replay, size_usd=SIZE_USD):
    """Each Eye rule as its own shadow test. The trades a rule blocks should lose, or the rule is noise."""
    def without_late_copy(ep):
        if LATE_COPY in (ep.get("note") or ""):
            return {**ep, "score": float(ep.get("score") or 0) + 12}
        return ep

    out = []
    flagged = sum(1 for ep in replay.ready if LATE_COPY in (ep.get("note") or ""))
    for book_id in (LADDER_ID, "loose-ladder"):
        book = book_by_id(book_id)
        kept, _ = replay.run(book, size_usd)
        free, _ = replay.run(book, size_usd, snap_fn=without_late_copy)
        seen = {id(t) for t in kept}
        blocked = [t["pnl"] for t in free if id(t) not in seen]
        ci = bootstrap_ci(blocked, seed=11) if blocked else None
        if len(blocked) < 30 or not ci:
            result = "too few blocked trades to tell"
        elif ci["high"] < 0:
            result = "helps: the trades it blocks lose"
        elif ci["low"] > 0:
            result = "hurts: the trades it blocks win"
        else:
            result = "no difference shown"
        out.append({
            "rule": "copy arrives late", "book": book_id, "flagged": flagged,
            "blocked": len(blocked), "blocked_mean": (sum(blocked) / len(blocked)) if blocked else None,
            "result": result,
        })
    out.append({
        "rule": "hostile-regime blocks", "book": "-", "flagged": None, "blocked": None, "blocked_mean": None,
        "result": "not replayable: it guards rule changes over time, not an entry. Judge it by the regime block",
    })
    return out


FEATURES = (
    "buy_sell_5m", "buy_sell_1h", "vol_accel", "holders", "holder_growth", "top10_rate",
    "dev_hold_rate", "creator_launches", "liq_mcap", "hour_sin", "hour_cos", "sol_trend_1h",
    "change_5m", "change_1h", "change_6h", "log_age", "sources", "buys_5m", "smart",
    "rug_score", "bubble_cluster", "rank",
)
MODEL_MIN = 500
MODEL_MIN_POS = 100
TEST_DAYS = 7


def _num(value):
    try:
        if value is None or value == "":
            return None
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def feature_row(ep):
    """Features as logged at the signal. None for coins recorded before feature logging started."""
    f = ep.get("features") or {}
    if not f:
        return None
    hour = (float(ep["started_at"]) % 86400) / 3600
    age = _num(ep.get("age_min"))
    values = {
        **{name: _num(f.get(name)) for name in FEATURES},
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "change_5m": _num(ep.get("change_5m")),
        "log_age": math.log1p(age) if age is not None and age >= 0 else None,
        "sources": float(len(ep.get("sources") or [])),
    }
    return [values[name] for name in FEATURES]


def _standardize(rows):
    k = len(FEATURES)
    means, stds = [], []
    for j in range(k):
        col = [r[j] for r in rows if r[j] is not None]
        mean = sum(col) / len(col) if col else 0.0
        var = sum((v - mean) ** 2 for v in col) / len(col) if col else 0.0
        means.append(mean)
        stds.append(math.sqrt(var) or 1.0)

    def apply(row):
        return [0.0 if v is None else max(-5.0, min(5.0, (v - m) / s)) for v, m, s in zip(row, means, stds)]
    return apply


def _fit(X, y, iters=150, lr=0.5, l2=1e-3):
    k = len(X[0])
    w = [0.0] * k
    b = 0.0
    n = len(X)
    for _ in range(iters):
        gw = [0.0] * k
        gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            err = 1 / (1 + math.exp(-max(-30.0, min(30.0, z)))) - yi
            gb += err
            for j in range(k):
                gw[j] += err * xi[j]
        b -= lr * gb / n
        w = [wj - lr * (g / n + l2 * wj) for wj, g in zip(w, gw)]
    return w, b


def auc(scores, labels):
    """Chance that a coin that hit 2x ranks above one that did not. 0.5 is random."""
    pos = sum(1 for v in labels if v)
    neg = len(labels) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    rank_pos = sum(r for r, v in zip(ranks, labels) if v)
    return (rank_pos - pos * (pos + 1) / 2) / (pos * neg)


def model_report(episodes, draws=200):
    """Learned score on logged features, trained before the last week and tested on that untouched week."""
    labeled = []
    for ep in episodes:
        if ep.get("hit15") is None:
            continue
        row = feature_row(ep)
        if row is not None:
            labeled.append((ep, row))
    positives = sum(1 for ep, _ in labeled if ep["hit15"])
    out = {"n": len(labeled), "positives": positives, "need": MODEL_MIN_POS, "target": "1.5x before a 35% drop",
           "status": "", "auc_model": None, "auc_score": None,
           "auc_low": None, "diff_low": None, "beats_random": False, "beats_score": False, "adopt": False,
           "weights": []}
    if positives < MODEL_MIN_POS:
        out["status"] = (
            f"collecting: {positives} of {MODEL_MIN_POS} positive examples "
            f"({len(labeled)} labeled coins with features)"
        )
        return out
    cut = max(ep["started_at"] for ep, _ in labeled) - TEST_DAYS * 86400
    train = [(ep, row) for ep, row in labeled if ep["started_at"] < cut]
    test = [(ep, row) for ep, row in labeled if ep["started_at"] >= cut]
    if sum(1 for ep, _ in train if ep["hit15"]) < MODEL_MIN_POS // 2 or len(test) < 100 \
            or sum(1 for ep, _ in test if ep["hit15"]) < 5:
        out["status"] = f"waiting for an untouched week: train {len(train)}, test {len(test)}"
        return out
    scale = _standardize([row for _, row in train])
    X = [scale(row) for _, row in train]
    y = [1.0 if ep["hit15"] else 0.0 for ep, _ in train]
    w, b = _fit(X, y)
    labels = [bool(ep["hit15"]) for ep, _ in test]
    model = [b + sum(wj * xj for wj, xj in zip(w, scale(row))) for _, row in test]
    score = [float(ep.get("score") or 0) for ep, _ in test]
    out["auc_model"] = auc(model, labels)
    out["auc_score"] = auc(score, labels)
    rng = random.Random(5)
    model_draws, diffs = [], []
    n = len(test)
    for _ in range(draws):
        pick = [rng.randrange(n) for _ in range(n)]
        a = auc([model[i] for i in pick], [labels[i] for i in pick])
        s = auc([score[i] for i in pick], [labels[i] for i in pick])
        if a is None or s is None:
            continue
        model_draws.append(a)
        diffs.append(a - s)
    model_draws.sort()
    diffs.sort()
    if model_draws:
        out["auc_low"] = model_draws[int(0.025 * (len(model_draws) - 1))]
        out["diff_low"] = diffs[int(0.025 * (len(diffs) - 1))]
    out["beats_random"] = out["auc_low"] is not None and out["auc_low"] > 0.5
    out["beats_score"] = out["diff_low"] is not None and out["diff_low"] > 0
    out["adopt"] = out["beats_random"] and out["beats_score"]
    out["weights"] = sorted(
        ({"feature": name, "weight": round(wj, 3)} for name, wj in zip(FEATURES, w)),
        key=lambda item: -abs(item["weight"]),
    )[:8]
    out["status"] = "adopt by hand" if out["adopt"] else "keep the hand-set score"
    return out


def stop_rule(model, books, tickets, every):
    rows = [b for b in list(books) + list(tickets) + [every] if b and b.get("n", 0) >= 30 and b.get("mean") is not None]
    best = max((b["mean"] for b in rows), default=None)
    if model["n"] < MODEL_MIN or model.get("auc_model") is None:
        verdict_text = (
            f"keep collecting ({model['n']} of {MODEL_MIN} labeled coins with features, "
            f"{model.get('positives', 0)} of {MODEL_MIN_POS} positives, model tested: "
            f"{'yes' if model.get('auc_model') is not None else 'no'})"
        )
    elif not model["beats_random"] and (best is None or best <= 0):
        verdict_text = (
            "stop adding agents: no feature set beats random on an untouched week and every book loses "
            "after costs. Public feeds polled every 45 seconds may be too slow against faster bots"
        )
    else:
        verdict_text = "continue: a feature set beats random or a book is positive after costs"
    return {"best_mean": best, "verdict": verdict_text}


def diagnose(outcomes, books, tickets, every, replay):
    """Which of three problems the book has. Each check lists its evidence. None means too little data."""
    out = []
    buckets = [b for b in outcomes["by_score"] if b["n"] >= 30 and b.get("rate_2x") is not None]
    traded = [b for b in books if b["n"] >= 30]
    main = max(traded, key=lambda b: b["n"]) if traded else None
    checks, evidence = [], []
    if len(buckets) >= 2:
        rates = [b["rate_2x"] for b in buckets]
        spread = max(rates) - min(rates)
        checks.append(spread < 0.02)
        evidence.append(f"2x share across score buckets spans {spread:.1%}")
    if main and main.get("random_percentile") is not None:
        pct = main["random_percentile"]
        checks.append(35 <= pct <= 65)
        evidence.append(f"{main['id']} random percentile {pct:.0f}")
    if main and every and every.get("n") and every.get("mean") is not None and main.get("mean") is not None:
        a = main["mean"] / main["size_usd"]
        b = every["mean"] / every["size_usd"]
        checks.append(abs(a - b) < 0.02)
        evidence.append(f"{main['id']} {a:+.1%} per dollar against buy-every {b:+.1%}")
    out.append({
        "problem": "signal is weak",
        "looks_like": (sum(checks) >= 2) if len(checks) >= 2 else None,
        "evidence": evidence,
    })

    checks, evidence = [], []
    parts = (every or {}).get("parts")
    if parts and parts["n"] >= 30:
        checks.append(parts["before_costs"] > 0 and parts["net"] < 0)
        evidence.append(f"buy-every before costs {parts['before_costs']:+.2f}, after costs {parts['net']:+.2f} per trade")
    ladder = book_by_id(LADDER_ID)
    small = _summary(replay.run(ladder, 5.5, taken_only=False)[0], 5.5)
    large = _summary(replay.run(ladder, 12.0, taken_only=False)[0], 12.0)
    if small["n"] >= 30 and large["n"] >= 30:
        checks.append(large["per_dollar"] > small["per_dollar"])
        evidence.append(f"every coin at $12 {large['per_dollar']:+.1%} per dollar, at $5.50 {small['per_dollar']:+.1%}")
    out.append({
        "problem": "costs eat a real edge",
        "looks_like": all(checks) if checks else None,
        "evidence": evidence,
    })

    checks, evidence = [], []
    if parts and parts["n"] >= 30:
        checks.append(parts["peak"] >= 1.5 and parts["close_x"] < 1.0)
        checks.append(parts["gave_back"] >= 0.40)
        evidence.append(
            f"median peak {parts['peak']:.2f}x, median close {parts['close_x']:.2f}x, "
            f"gave back gains {parts['gave_back']:.0%}"
        )
    out.append({
        "problem": "exits give gains back",
        "looks_like": all(checks) if checks else None,
        "evidence": evidence,
    })
    return out


def classify_desk_trade(buy, sells, closed, later_multiple=None):
    """Why a losing desk close looks the way it does. Winners are not classified."""
    try:
        final_x = float(closed.get("x") or 0)
        pnl = float(closed.get("sol_pnl") or 0)
    except (TypeError, ValueError):
        return None
    if pnl >= 0:
        return None
    note = " ".join((row.get("note") or "") for row in sells + [closed]).lower()
    peak = 0.0
    for row in sells:
        try:
            peak = max(peak, float(row.get("x") or 0))
        except (TypeError, ValueError):
            continue
    if final_x <= 0.35 or "rug" in note:
        return "rug"
    if peak >= 1.5 and final_x < 1.2:
        return "gave back gains"
    if later_multiple is not None and later_multiple >= 2 and final_x < 1.5:
        return "sold too early"
    if "agent cut" in note or "early" in note:
        return "sold too early"
    return "slow bleed"


def desk_loss_report(trades, later=None):
    """trades are desk ledger rows. later maps mint to the best multiple the lab saw after the buy."""
    later = later or {}
    by_mint = {}
    for row in trades:
        by_mint.setdefault(row.get("mint") or "", []).append(row)
    counts = {"rug": 0, "gave back gains": 0, "slow bleed": 0, "sold too early": 0}
    losers = 0
    for mint, rows in by_mint.items():
        buy = next((r for r in rows if r.get("event") == "BUY"), None)
        closed = next((r for r in reversed(rows) if r.get("event") == "CLOSED"), None)
        if not buy or not closed:
            continue
        sells = [r for r in rows if r.get("event") == "SELL"]
        label = classify_desk_trade(buy, sells, closed, later.get(mint))
        if not label:
            continue
        losers += 1
        counts[label] += 1
    return {"losers": losers, "counts": counts}
