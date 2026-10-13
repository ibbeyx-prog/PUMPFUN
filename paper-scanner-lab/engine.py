"""Replay rules on recorded scans. No network, no desk files, no orders."""
import random
from dataclasses import dataclass

FEE = 0.01
FLAT_USD = 0.20
SLIP_CAP = 0.35
ENTRY_DELAY_S = 45
TRACK_S = 4 * 3600
VANISH_LEFT = 0.10
SIZE_USD = 5.0
MIN_CHANGE = 5.0
CONFIRM = ("gmgn", "dexscreener", "birdeye")
HARD_WORDS = (
    "rug", "wash", "bundled", "thin liquidity", "mcap outside",
    "too new", "too old", "no liquidity",
)


@dataclass(frozen=True)
class Book:
    id: str
    name: str
    min_sources: int
    entry_score: int
    max_change_5m: float
    early_cut_x: float | None
    early_cut_min: float | None
    stop: float
    time_stop_min: float
    ladder: tuple
    runner: tuple | None = None


def _ladder():
    return ((2.0, 0.40), (3.5, 0.30), (5.0, 1.0))


def _books():
    entries = (
        ("strict", "Strict", 3, 80, 40),
        ("desk", "Desk", 3, 70, 45),
        ("loose", "Loose", 2, 65, 60),
    )
    exits = (
        ("cut", "cut fast", 0.75, 8, 0.35, 60, ()),
        ("ladder", "ladder", 0.80, 10, 0.35, 90, _ladder()),
        ("hold", "hold", None, None, 0.50, 180, ()),
    )
    out = []
    for eid, ename, sources, score, chase in entries:
        for xid, xname, cut_x, cut_min, stop, time_stop, ladder in exits:
            out.append(Book(
                f"{eid}-{xid}", f"{ename} / {xname}", sources, score, chase,
                cut_x, cut_min, stop, time_stop, ladder,
            ))
    out.append(Book(
        "desk-runner", "Desk / runner", 3, 70, 45,
        0.80, 10, 0.35, 90, (), (2.0, 0.5, 0.30),
    ))
    return tuple(out)


BOOKS = _books()


def slippage(size_usd, liq_usd):
    return min(SLIP_CAP, float(size_usd) / max(float(liq_usd or 0), 1.0))


def piece(entry_px, exit_px, size_usd, liq_usd):
    """One exit, including its $0.20. The entry's $0.20 is charged once by the caller."""
    slip = slippage(size_usd, liq_usd)
    entry_mult = (1 + slip) * (1 + FEE)
    exit_mult = max(0.0, (1 - slip) * (1 - FEE))
    if entry_px <= 0 or exit_px <= 0:
        return -0.90 * size_usd - FLAT_USD
    proceeds = (size_usd / entry_mult) * (exit_px / entry_px) * exit_mult
    return proceeds - size_usd - FLAT_USD


def round_trip(entry_px, exit_px, size_usd, liq_usd):
    """A full buy and sell: 1% each side, a $0.20 transaction each way."""
    return piece(entry_px, exit_px, size_usd, liq_usd) - FLAT_USD


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
    if not any(name in sources for name in CONFIRM):
        return False
    score = snap.get("score")
    if score is None or float(score) < book.entry_score:
        return False
    change = snap.get("change_5m")
    if change is None or not (MIN_CHANGE <= float(change) <= book.max_change_5m):
        return False
    age = snap.get("age_min")
    if age is not None and float(age) < 5:
        return False
    mcap = snap.get("mcap")
    if mcap is not None and not (6000 <= float(mcap) <= 800000):
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


def simulate(book, snap, path, size_usd=SIZE_USD):
    """Walk one 4-hour path. Entry is the first price at least 45 seconds after the scan."""
    start = float(snap["started_at"])
    end = start + TRACK_S
    entry = None
    for at, price in path:
        if at >= start + ENTRY_DELAY_S and price and price > 0:
            entry = (at, float(price))
            break
    if entry is None:
        return {"pnl": vanished_pnl(size_usd), "reason": "vanished", "multiple": VANISH_LEFT, "win": False}
    entry_at, entry_px = entry
    liq = snap.get("liq")
    left = 1.0
    tier = 0
    runner_peak = 1.0
    pnl = -FLAT_USD
    stop_seen = False
    cut_seen = False
    last_x = 1.0
    reason = "mark"
    points = [(at, px) for at, px in path if entry_at <= at <= end and px and px > 0]
    if not points:
        return {"pnl": vanished_pnl(size_usd), "reason": "vanished", "multiple": VANISH_LEFT, "win": False}
    if points[-1][0] < end - 15 * 60 and (end - points[-1][0]) > 15 * 60:
        vanished = True
    else:
        vanished = False

    def sell(frac, px, why):
        nonlocal left, pnl, reason
        frac = min(frac, left)
        if frac <= 0:
            return
        pnl += piece(entry_px, px, size_usd * frac, liq)
        left -= frac
        reason = why

    for at, px in points:
        last_x = px / entry_px
        age_min = (at - entry_at) / 60
        if last_x <= 1 - book.stop:
            if stop_seen:
                sell(left, px, "stop")
                break
            stop_seen = True
        else:
            stop_seen = False
        if book.early_cut_x and age_min >= book.early_cut_min and last_x <= book.early_cut_x and last_x < 2:
            if cut_seen:
                sell(left, px, "early-cut")
                break
            cut_seen = True
        else:
            cut_seen = False
        if age_min >= book.time_stop_min and last_x < 2:
            sell(left, px, "time-stop")
            break
        if book.runner:
            first_x, first_frac, trail = book.runner
            if tier == 0 and last_x >= first_x:
                sell(first_frac, px, f"runner {first_x:g}x")
                tier = 1
                runner_peak = last_x
            elif tier >= 1:
                runner_peak = max(runner_peak, last_x)
                if last_x <= runner_peak * (1 - trail):
                    sell(left, px, "trail")
                    break
            if left <= 1e-9:
                break
            continue
        while tier < len(book.ladder) and last_x >= book.ladder[tier][0] and left > 0:
            multiple, frac = book.ladder[tier]
            tier += 1
            take = left if frac >= 1 else frac
            sell(take, px, f"ladder {multiple:g}x")
            if left <= 1e-9:
                break
        if left <= 1e-9:
            break
    if left > 1e-9:
        if vanished:
            sell(left, entry_px * VANISH_LEFT, "vanished")
        else:
            sell(left, points[-1][1], "window")
    return {"pnl": pnl, "reason": reason, "multiple": last_x, "win": pnl > 0}


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
        groups.setdefault(key(row), []).append(row["forward"])
    out = []
    for name, values in groups.items():
        if not values:
            continue
        wins = sum(1 for v in values if v > 0)
        out.append({
            "name": name,
            "n": len(values),
            "mean": sum(values) / len(values),
            "win_rate": wins / len(values),
        })
    out.sort(key=lambda item: (-item["n"], item["name"]))
    return out


def outcome_tables(episodes):
    """Forward return from the delayed entry to the 4-hour mark, before a book's own exits."""
    rows = []
    for ep in episodes:
        if ep.get("forward") is None:
            continue
        rows.append(ep)
    return {
        "by_decision": _group(rows, lambda r: r.get("decision") or "unknown"),
        "by_score": _group(rows, lambda r: bucket_score(r.get("score"))),
        "by_sources": _group(rows, lambda r: str(min(3, len(r.get("sources") or []))) + ("+" if len(r.get("sources") or []) >= 3 else "")),
        "by_skip": _group(
            [r for r in rows if r.get("decision") == "skip"],
            lambda r: skip_reason(r.get("note"), "skip"),
        ),
    }


def forced_pnl(book, snap, path, size_usd=SIZE_USD):
    """Same exit style, but the coin is entered even if the entry rule would pass."""
    return simulate(book, snap, path, size_usd)["pnl"]


def run_books(episodes, size_usd=SIZE_USD):
    """Nine shadow books on the same recorded signals."""
    ready = [ep for ep in episodes if ep.get("path")]
    results = []
    for book in BOOKS:
        taken = []
        pool = []
        for ep in ready:
            pool.append(forced_pnl(book, ep, ep["path"], size_usd))
            if would_enter(book, ep):
                trade = simulate(book, ep, ep["path"], size_usd)
                taken.append(trade["pnl"])
        seed = sum(ord(ch) for ch in book.id)
        ci = bootstrap_ci(taken, seed=seed)
        total = sum(taken)
        results.append({
            "id": book.id,
            "name": book.name,
            "n": len(taken),
            "total": total,
            "mean": (total / len(taken)) if taken else None,
            "win_rate": (sum(1 for p in taken if p > 0) / len(taken)) if taken else None,
            "ci": ci,
            "verdict": verdict(len(taken), ci),
            "random_percentile": random_percentile(total, pool, len(taken), seed=seed),
        })
    results.sort(key=lambda row: (row["total"] is not None, row["total"] or 0), reverse=True)
    return results


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
