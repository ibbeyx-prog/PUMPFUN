"""
Paper Scanner Lab. Read-only sidecar.

It reads the desk API and writes only its own sqlite file. It does not trade
and it does not open the desk's ledger, bank, config, or .env.
"""
import calendar
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR") or os.path.join(HERE, "data")
DB_PATH = os.path.join(DATA, "lab.sqlite")
SOL_MINT = "So11111111111111111111111111111111111111112"
LOCK = threading.Lock()
REPORT_LOCK = threading.Lock()
_SOL = {"at": 0.0, "usd": 0.0}


def env(name, default=""):
    return os.environ.get(name, default).strip()


def ledger_offset():
    try:
        return float(env("LEDGER_TZ_OFFSET_H", "0") or 0) * 3600
    except ValueError:
        return 0.0


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self._init()

    def _init(self):
        self.db.executescript(
            """
            create table if not exists hits (
              id integer primary key,
              scanned_at real not null,
              recorded_at real not null,
              mint text not null,
              symbol text not null default '',
              score real,
              decision text not null default '',
              note text not null default '',
              sources text not null default '[]',
              mcap real,
              liq real,
              change_5m real,
              price_sol real,
              age_min real,
              rug_label text not null default ''
            );
            create table if not exists episodes (
              id integer primary key,
              mint text not null,
              symbol text not null default '',
              started_at real not null,
              track_until real not null,
              score real,
              decision text not null default '',
              note text not null default '',
              sources text not null default '[]',
              mcap real,
              liq real,
              change_5m real,
              age_min real,
              rug_label text not null default '',
              done integer not null default 0
            );
            create table if not exists prices (
              episode_id integer not null,
              at real not null,
              price real not null,
              primary key (episode_id, at)
            );
            create table if not exists desk_trades (
              id integer primary key,
              time_text text not null default '',
              event text not null default '',
              mint text not null default '',
              wallet text not null default '',
              price_sol real,
              x real,
              sol_pnl real,
              note text not null default ''
            );
            create table if not exists meta (
              k text primary key,
              v text not null
            );
            """
        )
        for table in ("hits", "episodes"):
            cols = {row["name"] for row in self.db.execute(f"pragma table_info({table})")}
            if "features" not in cols:
                self.db.execute(f"alter table {table} add column features text not null default '{{}}'")
            if table == "episodes" and "last_priced" not in cols:
                self.db.execute("alter table episodes add column last_priced real not null default 0")
        self.db.execute("create index if not exists prices_episode on prices (episode_id, at)")
        self.db.commit()

    def meta(self, key, default=None):
        row = self.db.execute("select v from meta where k = ?", (key,)).fetchone()
        return default if row is None else row["v"]

    def set_meta(self, key, value):
        self.db.execute(
            "insert into meta(k, v) values(?, ?) on conflict(k) do update set v = excluded.v",
            (key, value),
        )
        self.db.commit()

    def seen_scan(self, scanned_at):
        return self.meta("last_scanned_at") == f"{float(scanned_at):.3f}"

    def add_hit(self, row):
        self.db.execute(
            """insert into hits(scanned_at, recorded_at, mint, symbol, score, decision, note,
               sources, mcap, liq, change_5m, price_sol, age_min, rug_label, features)
               values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["scanned_at"], row["recorded_at"], row["mint"], row["symbol"], row["score"],
                row["decision"], row["note"], json.dumps(row["sources"]), row["mcap"], row["liq"],
                row["change_5m"], row["price_sol"], row["age_min"], row["rug_label"],
                json.dumps(row.get("features") or {}),
            ),
        )

    def open_episode(self, row):
        now = row["recorded_at"]
        live = self.db.execute(
            "select id from episodes where mint = ? and track_until > ?",
            (row["mint"], now),
        ).fetchone()
        if live:
            return False
        self.db.execute(
            """insert into episodes(mint, symbol, started_at, track_until, score, decision, note,
               sources, mcap, liq, change_5m, age_min, rug_label, features)
               values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["mint"], row["symbol"], now, now + engine.TRACK_S, row["score"], row["decision"],
                row["note"], json.dumps(row["sources"]), row["mcap"], row["liq"], row["change_5m"],
                row["age_min"], row["rug_label"], json.dumps(row.get("features") or {}),
            ),
        )
        return True

    def commit(self):
        self.db.commit()

    def replace_trades(self, rows):
        self.db.execute("delete from desk_trades")
        for row in rows:
            self.db.execute(
                """insert into desk_trades(time_text, event, mint, wallet, price_sol, x, sol_pnl, note)
                   values(?,?,?,?,?,?,?,?)""",
                (
                    str(row.get("time") or ""), str(row.get("event") or ""), str(row.get("mint") or ""),
                    str(row.get("wallet") or ""), _num(row.get("price_sol")), _num(row.get("x")),
                    _num(row.get("sol_pnl")), str(row.get("note") or ""),
                ),
            )
        self.db.commit()

    def due_episodes(self, now, limit=300):
        """Least recently priced first, so a new coin gets its first quote within a minute."""
        return self.db.execute(
            """select id, mint from episodes
               where done = 0 and track_until > ?
               order by last_priced asc, started_at desc limit ?""",
            (now - 60, limit),
        ).fetchall()

    def touch_priced(self, episode_ids, now):
        self.db.executemany("update episodes set last_priced = ? where id = ?", [(now, i) for i in episode_ids])

    def mark_done(self, now):
        self.db.execute("update episodes set done = 1 where done = 0 and track_until <= ?", (now,))
        self.db.commit()

    def add_price(self, episode_id, at, price):
        self.db.execute(
            "insert into prices(episode_id, at, price) values(?,?,?) on conflict(episode_id, at) do nothing",
            (episode_id, at, price),
        )

    def counts(self):
        hits = self.db.execute("select count(*) c from hits").fetchone()["c"]
        episodes = self.db.execute("select count(*) c from episodes").fetchone()["c"]
        done = self.db.execute("select count(*) c from episodes where done = 1").fetchone()["c"]
        return {"hits": hits, "episodes": episodes, "done": done}

    def span_days(self):
        row = self.db.execute("select min(started_at) lo, max(started_at) hi, count(*) n from episodes").fetchone()
        if not row or not row["n"] or row["lo"] is None:
            return 0.0
        return (float(row["hi"]) - float(row["lo"])) / 86400.0

    def episodes_for_report(self):
        rows = self.db.execute("select * from episodes").fetchall()
        out = []
        for row in rows:
            path = [
                (r["at"], r["price"])
                for r in self.db.execute(
                    "select at, price from prices where episode_id = ? order by at", (row["id"],)
                )
            ]
            item = {
                "mint": row["mint"],
                "symbol": row["symbol"],
                "started_at": row["started_at"],
                "score": row["score"],
                "decision": row["decision"],
                "note": row["note"],
                "sources": json.loads(row["sources"] or "[]"),
                "mcap": row["mcap"],
                "liq": row["liq"],
                "change_5m": row["change_5m"],
                "age_min": row["age_min"],
                "rug_label": row["rug_label"],
                "features": json.loads(row["features"] or "{}"),
                "path": path,
                "done": bool(row["done"]),
                "forward": None,
                "hit2x": None,
                "hit15": None,
            }
            entry = engine.entry_point(path, row["started_at"], "delay") if path else None
            if entry:
                end_px = next((px for _, px in reversed(path) if px and px > 0), 0)
                item["forward"] = engine.round_trip(entry[1], end_px, engine.SIZE_USD, row["liq"])
                item["hit2x"] = engine.label_2x(path, row["started_at"])
                item["hit15"] = engine.label_15(path, row["started_at"])
            out.append(item)
        _creator_launches(out)
        return out

    def timely_share(self):
        """Share of finished coins whose first quote came inside the entry window."""
        row = self.db.execute(
            """select count(*) n, sum(case when first_at <= started_at + ? then 1 else 0 end) ok
               from (select e.started_at, min(p.at) first_at from episodes e
                     join prices p on p.episode_id = e.id and p.price > 0
                     where e.done = 1 group by e.id)""",
            (engine.ENTRY_DELAY_S + engine.ENTRY_WINDOW_S,),
        ).fetchone()
        return {"priced": row["n"] or 0, "timely": row["ok"] or 0}

    def trades(self):
        return [dict(row) for row in self.db.execute("select * from desk_trades order by id")]

def _creator_launches(episodes):
    """How many earlier coins the lab saw from the same creator. Counts only coins started before this one."""
    seen = {}
    for ep in sorted(episodes, key=lambda e: e["started_at"]):
        creator = (ep.get("features") or {}).get("creator")
        if not creator:
            continue
        mints = seen.setdefault(creator, set())
        ep["features"]["creator_launches"] = len(mints - {ep["mint"]})
        mints.add(ep["mint"])


def _num(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row, *names):
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def record_scan(store, payload, now=None):
    """Map one /api/candidates payload into hits and 4-hour episodes.

    The desk currently sends candidates[].mint, symbol, score, decision, note,
    sources, mcap, liq, change_5m, price_sol, age_min, rug_label, and scanned_at
    on the payload. If a future desk renames a field, change the _first() names here.
    """
    now = time.time() if now is None else now
    scanned_at = _num(_first(payload, "scanned_at", "scannedAt")) or now
    if store.seen_scan(scanned_at):
        return 0
    rows = payload.get("candidates")
    if rows is None:
        rows = payload.get("data") or []
    added = 0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        mint = str(_first(raw, "mint", "address", "tokenAddress") or "").strip()
        if not mint:
            continue
        sources = _first(raw, "sources") or []
        if isinstance(sources, str):
            sources = [part for part in sources.split("+") if part]
        row = {
            "scanned_at": scanned_at,
            "recorded_at": now,
            "mint": mint,
            "symbol": str(_first(raw, "symbol", "name") or "")[:32],
            "score": _num(_first(raw, "score")),
            "decision": str(_first(raw, "decision") or ""),
            "note": str(_first(raw, "note") or "")[:300],
            "sources": list(sources),
            "mcap": _num(_first(raw, "mcap", "marketCap", "market_cap")),
            "liq": _num(_first(raw, "liq", "liquidity")),
            "change_5m": _num(_first(raw, "change_5m", "change5m", "price_change_percent5m")),
            "price_sol": _num(_first(raw, "price_sol", "priceSol")),
            "age_min": _num(_first(raw, "age_min", "ageMin")),
            "rug_label": str(_first(raw, "rug_label", "rugLabel") or "")[:48],
            "features": raw.get("features") if isinstance(raw.get("features"), dict) else {},
        }
        store.add_hit(row)
        if store.open_episode(row):
            added += 1
    store.set_meta("last_scanned_at", f"{float(scanned_at):.3f}")
    store.commit()
    return added


def _get(url, token=""):
    headers = {"User-Agent": "paper-scanner-lab", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_desk(store):
    base = env("SCANNER_URL").rstrip("/")
    token = env("DASH_TOKEN")
    if not base:
        print("SCANNER_URL is not set")
        return
    if not token or "dashboard token" in token.lower() or token.lower().startswith("paste"):
        print("DASH_TOKEN is not the desk login password. On the deployed site, that is the password you type at Paper Scanner before Enter.")
        return
    try:
        payload = _get(base + "/api/candidates", token)
        added = record_scan(store, payload)
        trades = _get(base + "/api/trades?limit=500", token)
        if isinstance(trades, list):
            store.replace_trades(trades)
        fetch_quotes(store, base, token)
        print(f"recorded scan, new episodes {added}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("desk read failed: HTTP 401. The desk rejected DASH_TOKEN.")
        else:
            print(f"desk read failed: HTTP {exc.code}")
    except Exception as exc:
        print("desk read failed:", type(exc).__name__)


def fetch_quotes(store, base, token):
    """The desk's Jupiter quote log summary. An older desk without /api/quotes is skipped quietly."""
    try:
        data = _get(base + "/api/quotes", token)
    except Exception:
        return
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k != "rows"}
        data["fetched_at"] = time.time()
        store.set_meta("desk_quotes", json.dumps(data))


def quote_calibration(store, size_usd=engine.SIZE_USD, min_ok=30):
    """Extra dollars per round trip that real Jupiter routes cost beyond the paper fill.

    Only a positive median gap counts. With fewer than 30 good quotes per side the costs are not calibrated.
    """
    try:
        data = json.loads(store.meta("desk_quotes") or "null")
    except ValueError:
        data = None
    out = {"calibrated": False, "shift_usd": 0.0, "summary": data}
    if not data:
        out["why"] = "no quote log from the desk yet"
        return out
    sides = data.get("sides") or {}
    buy, sell = sides.get("buy") or {}, sides.get("sell") or {}
    if (buy.get("ok") or 0) < min_ok or (sell.get("ok") or 0) < min_ok:
        out["why"] = f"needs {min_ok} good quotes per side (buy {buy.get('ok') or 0}, sell {sell.get('ok') or 0})"
        return out
    gap = max(0.0, buy.get("median_gap") or 0.0) + max(0.0, sell.get("median_gap") or 0.0)
    out.update(calibrated=True, shift_usd=round(gap * size_usd, 4), why="median buy and sell gaps from the desk quote log")
    return out


def _sol_usd():
    now = time.time()
    if _SOL["usd"] and now - _SOL["at"] < 60:
        return _SOL["usd"]
    try:
        data = _get(f"https://api.dexscreener.com/tokens/v1/solana/{SOL_MINT}")
        price = 0.0
        for pair in data if isinstance(data, list) else []:
            try:
                price = max(price, float(pair.get("priceUsd") or 0))
            except (TypeError, ValueError):
                continue
        if 20 <= price <= 1000:
            _SOL.update(at=now, usd=price)
    except Exception:
        pass
    return _SOL["usd"]


def _token_prices(mints):
    if not mints:
        return {}
    joined = ",".join(mints[:30])
    data = _get(f"https://api.dexscreener.com/tokens/v1/solana/{joined}")
    sol = _sol_usd()
    best = {}
    for pair in data if isinstance(data, list) else []:
        mint = ((pair.get("baseToken") or {}).get("address")) or ""
        if mint not in mints:
            continue
        try:
            usd = float(pair.get("priceUsd") or 0)
        except (TypeError, ValueError):
            usd = 0.0
        if not usd and sol:
            try:
                usd = float(pair.get("priceNative") or 0) * sol
            except (TypeError, ValueError):
                usd = 0.0
        if usd > 0 and usd > best.get(mint, 0):
            best[mint] = usd
    return best


def price_due(store):
    now = time.time()
    store.mark_done(now)
    rows = store.due_episodes(now)
    if not rows:
        return
    prices = {}
    mints = list(dict.fromkeys(row["mint"] for row in rows))
    asked = set()
    for i in range(0, len(mints), 30):
        batch = mints[i:i + 30]
        try:
            prices.update(_token_prices(batch))
            asked.update(batch)
        except Exception as exc:
            print("price read failed:", type(exc).__name__)
            break
    rows = [row for row in rows if row["mint"] in asked]
    store.touch_priced([row["id"] for row in rows], now)
    for row in rows:
        price = prices.get(row["mint"])
        if price:
            store.add_price(row["id"], now, price)
        elif now - _episode_start(store, row["id"]) > engine.ENTRY_DELAY_S + 20 * 60:
            # No quote after the entry delay: remember a vanished mark once.
            if not _has_price(store, row["id"]):
                store.add_price(row["id"], now, 0.0)
    store.commit()


def _episode_start(store, episode_id):
    row = store.db.execute("select started_at from episodes where id = ?", (episode_id,)).fetchone()
    return row["started_at"] if row else time.time()


def _has_price(store, episode_id):
    row = store.db.execute("select 1 from prices where episode_id = ?", (episode_id,)).fetchone()
    return row is not None


def _when(name, default):
    text = env(name, default) or default
    for value in (text, default):
        try:
            return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
    return 0.0


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def research_windows():
    return {
        "explore_from": _when("LAB_EXPLORE_FROM", "2026-10-15T00:00:00Z"),
        "freeze_at": _when("LAB_FREEZE_AT", "2026-10-21T00:00:00Z"),
        "confirm_until": _when("LAB_CONFIRM_UNTIL", "2026-10-28T00:00:00Z"),
    }


def research(store, done, now):
    """Explore week picks the top 3 books by paired difference. The picks freeze once and are never recomputed.
    The confirm week judges only the frozen picks, against buy-every-name and hold-SOL on the same week."""
    w = research_windows()
    explore = engine.Replay([ep for ep in done if w["explore_from"] <= ep["started_at"] < w["freeze_at"]])
    confirm = engine.Replay([ep for ep in done if w["freeze_at"] <= ep["started_at"] < w["confirm_until"]])
    explore_rows = engine.run_books(explore)
    leaders = engine.pick_leaders(explore_rows)
    try:
        frozen = json.loads(store.meta("frozen_picks") or "null")
    except ValueError:
        frozen = None
    # Wait until the last explore-week coin has finished its 4-hour window.
    if frozen is None and now >= w["freeze_at"] + engine.TRACK_S:
        frozen = {
            "at": _iso(now),
            "picks": leaders,
            "tried": len(engine.BOOKS),
            "explore": {
                r["id"]: {"n": r["n"], "mean": r["mean"], "paired": r["paired"]} for r in explore_rows
            },
        }
        store.set_meta("frozen_picks", json.dumps(frozen))
    confirm_rows = []
    for book_id in (frozen or {}).get("picks") or []:
        book = engine.book_by_id(book_id)
        taken, pool = confirm.run(book, engine.SIZE_USD)
        row = engine._row(book.id, book.name, taken, pool, engine.SIZE_USD)
        row["paired"] = engine.paired_vs_reference(confirm, book)
        confirm_rows.append(row)
    base = engine.baselines(confirm, engine.SIZE_USD)
    return {
        "windows": {k: _iso(v) for k, v in w.items()},
        "phase": (
            "before explore" if now < w["explore_from"]
            else "explore" if now < w["freeze_at"]
            else "confirm" if now < w["confirm_until"] + engine.TRACK_S
            else "done"
        ),
        "explore_coins": len(explore.ready),
        "confirm_coins": len(confirm.ready),
        "explore": explore_rows,
        "leaders": leaders,
        "tried": len(engine.BOOKS),
        "frozen": frozen,
        "confirm": confirm_rows,
        "confirm_every": base[1],
    }


VERDICT_MIN_N = 50


def weekly_verdict(res, cal, now):
    """Edge found, Not yet, No edge, or Costs only. Numbers use the quote-calibrated cost shift."""
    shift = cal["shift_usd"] if cal["calibrated"] else 0.0
    every = res["confirm_every"]
    every_mean = (every.get("mean") or 0.0) - shift if every.get("n") else None
    rows = []
    for r in res["confirm"]:
        parts = r.get("parts") or {}
        ci = r.get("ci") or {}
        rows.append({
            "id": r["id"],
            "n": r["n"],
            "mean": None if r["mean"] is None else r["mean"] - shift,
            "low": None if ci.get("low") is None else ci["low"] - shift,
            "high": None if ci.get("high") is None else ci["high"] - shift,
            "before_costs": parts.get("before_costs"),
            "costs": None if parts.get("costs") is None else parts["costs"] - shift,
            "paired": r.get("paired"),
        })
    out = {"rows": rows, "every_mean": every_mean, "shift_usd": shift, "calibrated": cal["calibrated"]}
    w = research_windows()
    if not res.get("frozen"):
        return {**out, "verdict": "Not yet", "why": f"picks freeze after {res['windows']['freeze_at']} once the explore week's coins finish"}
    if not res["frozen"].get("picks"):
        return {**out, "verdict": "Not yet", "why": "no book had 30 explore-week trades with a paired difference, so nothing froze"}
    edge = [
        r for r in rows
        if r["n"] >= VERDICT_MIN_N and r["low"] is not None and r["low"] > 0
        and r["mean"] > max(0.0, every_mean or 0.0)
    ]
    positive = [r for r in rows if r["mean"] is not None and r["mean"] > 0]
    gross = [r for r in rows if (r["before_costs"] or 0) > 0]
    week_over = now >= w["confirm_until"] + engine.TRACK_S
    if edge and cal["calibrated"]:
        best = max(edge, key=lambda r: r["low"])
        return {**out, "verdict": "Edge found",
                "why": f"{best['id']}: {best['n']} confirm trades, CI low ${best['low']:+.3f} per trade after calibrated costs, beats buy-every-name and hold-SOL"}
    if edge:
        return {**out, "verdict": "Not yet", "why": f"{edge[0]['id']} passes on paper costs, but costs are not calibrated: {cal['why']}"}
    if positive:
        r = max(positive, key=lambda x: x["mean"])
        return {**out, "verdict": "Not yet",
                "why": f"{r['id']} is positive (${r['mean']:+.3f} per trade) but has {r['n']} trades or a CI that spans zero; run one more confirm week"}
    if not week_over:
        return {**out, "verdict": "Not yet", "why": f"confirm week runs until {res['windows']['confirm_until']}"}
    if gross:
        return {**out, "verdict": "Costs only",
                "why": "price moves are positive before costs but costs eat them; test $8 and $12 tickets and fewer-trade rules"}
    return {**out, "verdict": "No edge",
            "why": "no frozen book is positive after costs and gross moves do not beat cost drag; stop the live plan and keep the Lab as research"}


def readiness(store, books):
    """The desk refuses live trading until this object says ready."""
    row = next((book for book in books if book.get("id") == engine.REAL_DESK_ID), None) or {}
    ci = row.get("ci") or {}
    low = ci.get("low")
    pct = row.get("random_percentile")
    n = row.get("n") or 0
    span = store.span_days()
    ready = (
        n >= 100
        and span >= 14
        and low is not None
        and low > 0
        and pct is not None
        and pct >= 90
    )
    return {
        "book": engine.REAL_DESK_ID,
        "closes": n,
        "span_days": round(span, 2),
        "ci_low": low,
        "random_percentile": pct,
        "ready": ready,
    }


def build_report(store, now=None):
    now = time.time() if now is None else now
    episodes = store.episodes_for_report()
    # A coin still inside its 4-hour window would look vanished, so only finished coins are replayed.
    done = [ep for ep in episodes if ep["done"]]
    replay = engine.Replay(done)
    books = engine.run_books(replay)
    real = engine.run_real_desk(replay)
    tickets = engine.ticket_books(replay, books)
    base = engine.baselines(replay)
    res = research(store, done, now)
    cal = quote_calibration(store)
    every = base[1]
    outcomes = engine.outcome_tables(done)
    model = engine.model_report(done)
    later = {}
    for ep in episodes:
        first = next((px for _, px in ep["path"] if px), 0)
        if first:
            later[ep["mint"]] = max(px for _, px in ep["path"]) / first
    losses = engine.desk_loss_report(store.trades(), later)
    counts = store.counts()
    timely = store.timely_share()
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "counts": counts,
        "timely": timely,
        "sample": engine.sample_label(sum(1 for ep in done if ep.get("hit2x") is not None)),
        "outcomes": outcomes,
        "books": books,
        "real_desk": real,
        "tickets": tickets,
        "baselines": base,
        "research": res,
        "quotes": cal,
        "verdict": weekly_verdict(res, cal, now),
        "diagnosis": engine.diagnose(outcomes, books, tickets, every, replay),
        "timing": engine.entry_timing(replay),
        "regime": engine.regime(replay, now),
        "edges": engine.score_edges(replay),
        "rules": engine.rule_tests(replay),
        "model": model,
        "stop_rule": engine.stop_rule(model, books, tickets, every),
        "readiness": readiness(store, [real]),
        "desk_losses": losses,
        "hypotheses": hypotheses(books, losses, counts),
        "fills": {
            "size_usd": engine.SIZE_USD,
            "fee_per_side": engine.FEE,
            "flat_usd": engine.FLAT_USD,
            "slippage": "3% + 2 x size / liquidity, capped at 80%",
            "entry_delay_s": engine.ENTRY_DELAY_S,
            "entry_window_s": engine.ENTRY_WINDOW_S,
            "track_hours": 4,
        },
    }
    return report


_REPORT = {"at": 0.0, "report": None}
REPORT_TTL_S = 300


def cached_report(store):
    """The full replay is heavy on a large sample. Rebuild at most every five minutes."""
    if _REPORT["report"] is None or time.time() - _REPORT["at"] > REPORT_TTL_S:
        _REPORT["report"] = build_report(store)
        _REPORT["at"] = time.time()
    return _REPORT["report"]


def hypotheses(books, losses, counts):
    key = env("ANTHROPIC_API_KEY")
    if not key:
        return []
    brief = {
        "episodes": counts.get("episodes"),
        "books": [
            {"name": b["name"], "n": b["n"], "total": b["total"], "verdict": b["verdict"]}
            for b in books[:5]
        ],
        "desk_losses": losses,
    }
    body = {
        "model": env("EYE_MODEL", "claude-sonnet-5-5"),
        "max_tokens": 400,
        "messages": [{
            "role": "user",
            "content": (
                "You are writing hypotheses, not instructions. Given this paper-lab summary, "
                "reply with JSON only: {\"hypotheses\":[\"...\"]} with 2 or 3 short sentences. "
                "Do not invent numbers that are not in the summary.\n"
                + json.dumps(brief)
            ),
        }],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode())
        text = "\n".join(
            block.get("text") or "" for block in data.get("content") or [] if block.get("type") == "text"
        )
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1]) if start >= 0 else {}
        return [str(item)[:240] for item in (parsed.get("hypotheses") or [])][:3]
    except Exception as exc:
        return [f"Hypotheses unavailable ({type(exc).__name__})."]


def format_report(report):
    counts = report["counts"]
    timely = report.get("timely") or {}
    fills = report.get("fills") or {}
    lines = [
        f"Paper Scanner Lab  {report['generated_at']}",
        f"Sample: {report['sample']}  scan rows {counts['hits']}  coins {counts['episodes']}  finished {counts['done']}",
        f"Coins with a quote inside the entry window: {timely.get('timely', 0)} of {timely.get('priced', 0)} priced. "
        "Coins without one are not traded, as the desk would skip them.",
        f"Fills: slippage {fills.get('slippage', '-')}, 1% fee per side, $0.20 per transaction, "
        "45s entry delay, vanished tokens ~90% loss. Same rules as the desk.",
        "",
    ]
    lines.extend(_verdict_lines(report))
    lines.append("")
    lines.append("Diagnosis")
    for item in report.get("diagnosis") or []:
        state = {True: "looks like it", False: "does not look like it", None: "too little data"}[item["looks_like"]]
        lines.append(f"  {item['problem']}: {state}")
        lines.extend(f"    {text}" for text in item["evidence"])
    lines.append("")
    lines.append("Profit and loss per trade (mean dollars)")
    lines.append("  book                     n   move   stop gap  slippage    fee   $0.20  gross  costs     net  peak  close  gave back")
    rows = [b for b in [report.get("real_desk") or {}] + report["books"] if b.get("parts")]
    rows += [b for b in report.get("tickets") or [] if b.get("parts")]
    rows += [b for b in report.get("baselines") or [] if b.get("parts")]
    if not rows:
        lines.append("  none yet")
    for book in rows:
        p = book["parts"]
        lines.append(
            f"  {book['id'][:22]:<22} {p['n']:>4} {p['move']:>6.2f} {p['stop_gap']:>9.2f} {p['slippage']:>9.2f} "
            f"{p['fee']:>6.2f} {p['flat']:>6.2f} {p['before_costs']:>6.2f} {p['costs']:>6.2f} "
            f"{p['net']:>7.2f} {p['peak']:>5.2f} {p['close_x']:>6.2f} {p['gave_back']:>9.0%}"
        )
    lines.append("")
    lines.append("Outcomes by decision")
    lines.extend(_table(report["outcomes"]["by_decision"]))
    lines.append("")
    lines.append("Outcomes by score")
    lines.extend(_table(report["outcomes"]["by_score"]))
    lines.append("")
    lines.append("Outcomes by source count")
    lines.extend(_table(report["outcomes"]["by_sources"]))
    lines.append("")
    lines.append("Skip reasons")
    lines.extend(_table(report["outcomes"]["by_skip"]))
    lines.append("")
    lines.append("Research books (no cooldown, scan, or open limits) and the real desk book")
    lines.append("  paired = dollars per signal against the filters-only ladder on the same signals")
    for book in [report.get("real_desk")] + report["books"]:
        if not book:
            continue
        ci = book["ci"] or {}
        pct = book["random_percentile"]
        paired = book.get("paired") or {}
        lines.append(
            f"{book['name']}: n={book['n']} total={_money(book['total'])} "
            f"mean={_money(book['mean'])} win={_pct(book['win_rate'])} "
            f"CI={_money(ci.get('low'))}..{_money(ci.get('high'))} "
            f"{book['verdict']}"
            + (f"  random percentile {pct:.0f}" if pct is not None else "")
            + (f"  paired {_signed(paired['mean'])} ({_signed(paired['low'])}..{_signed(paired['high'])})"
               if paired.get("mean") is not None else "")
        )
    lines.extend(_research_lines(report))
    lines.append("")
    lines.append("Ticket size, top 3 entry rules on the ladder exit")
    for book in report.get("tickets") or []:
        lines.append(
            f"{book['name']}: n={book['n']} total={_money(book['total'])} "
            f"mean={_money(book['mean'])} win={_pct(book['win_rate'])} {book['verdict']}"
        )
    lines.append("")
    lines.append("Baselines")
    for book in report.get("baselines") or []:
        lines.append(f"{book['name']}: n={book['n']} total={_money(book['total'])} mean={_money(book['mean'])}")
    lines.append("")
    lines.append("Entry timing, ladder exits at $5.50")
    for row in report.get("timing") or []:
        lines.append(
            f"  {row['group']}, {row['entry']}: n={row['n']} mean={_money(row['mean'])} "
            f"per dollar={_pct1(row['per_dollar'])} win={_pct(row['win_rate'])}"
        )
    reg = report.get("regime") or {}
    lines.append("")
    lines.append(
        f"Market: 2x share over 24h {_pct1(reg.get('rate_24h'))} of {reg.get('n_24h', 0)} coins, "
        f"pause line {_pct1(reg.get('threshold'))}, pause {'yes' if reg.get('pause') else 'no'}. {reg.get('why', '')}"
    )
    for name in ("cold", "warm"):
        side = reg.get(name)
        if side:
            lines.append(f"  {name} markets: n={side['n']} mean={_money(side['mean'])} win={_pct(side['win_rate'])}")
    lines.append("")
    lines.append("Score edge at $5.50 (before costs, costs, net)")
    for row in report.get("edges") or []:
        pays = {True: "pays", False: "does not pay", None: "too few"}[row["pays"]]
        lines.append(
            f"  {row['bucket']}: n={row['n']} {_money(row['before_costs'])} {_money(row['costs'])} "
            f"{_money(row['net'])} {pays}"
        )
    lines.append("")
    lines.append("Eye rules as shadow tests")
    for row in report.get("rules") or []:
        if row["blocked"] is None:
            lines.append(f"  {row['rule']}: {row['result']}")
        else:
            lines.append(
                f"  {row['rule']} on {row['book']}: flagged {row['flagged']} coins, blocked {row['blocked']} trades "
                f"mean {_money(row['blocked_mean'])}. {row['result']}"
            )
    model = report.get("model") or {}
    lines.append("")
    lines.append(f"Learned score: {model.get('status', '')}")
    if model.get("auc_model") is not None:
        lines.append(
            f"  untouched week: model AUC {model['auc_model']:.3f} (low {model['auc_low']:.3f}), "
            f"hand score AUC {model['auc_score']:.3f}, difference low {model['diff_low']:+.3f}"
        )
        lines.append("  top weights: " + ", ".join(f"{w['feature']} {w['weight']:+.2f}" for w in model["weights"]))
    stop = report.get("stop_rule") or {}
    lines.append(f"Stop rule: {stop.get('verdict', '')}")
    gate = report.get("readiness") or {}
    lines.append("")
    lines.append(
        "Live gate: "
        + ("open" if gate.get("ready") else "closed")
        + f"  {gate.get('book')} n={gate.get('closes')}  span {gate.get('span_days')}d"
    )
    lines.extend(_quote_lines(report))
    losses = report["desk_losses"]
    lines.append("")
    lines.append(f"Desk losing closes: {losses['losers']}")
    for name, count in losses["counts"].items():
        lines.append(f"  {name}: {count}")
    if report["hypotheses"]:
        lines.append("")
        lines.append("Hypotheses (not findings)")
        lines.extend(f"  {item}" for item in report["hypotheses"])
    return "\n".join(lines)


def _verdict_lines(report):
    v = report.get("verdict") or {}
    res = report.get("research") or {}
    w = res.get("windows") or {}
    lines = [
        f"Weekly verdict: {v.get('verdict', '-')}. {v.get('why', '')}",
        f"  phase {res.get('phase', '-')}: explore {w.get('explore_from', '-')} to {w.get('freeze_at', '-')}, "
        f"confirm to {w.get('confirm_until', '-')}. Costs "
        + (f"calibrated, +{_money(v.get('shift_usd'))} per trade from quotes" if v.get("calibrated") else "not calibrated yet"),
    ]
    for r in v.get("rows") or []:
        lines.append(
            f"  {r['id']}: n={r['n']} mean={_signed(r['mean'])} CI={_signed(r['low'])}..{_signed(r['high'])} "
            f"gross={_signed(r['before_costs'])} costs={_signed(r['costs'])}"
        )
    if v.get("rows"):
        lines.append(f"  buy every name, confirm week: {_signed(v.get('every_mean'))} per trade. Hold SOL: $0.00.")
    return lines


def _research_lines(report):
    res = report.get("research") or {}
    if not res:
        return []
    lines = ["", f"Explore week: {res.get('explore_coins', 0)} finished coins, {res.get('tried', 0)} books tried"]
    for r in (res.get("explore") or []) if res.get("explore_coins") else []:
        paired = r.get("paired") or {}
        lines.append(
            f"  {r['id']}: n={r['n']} mean={_signed(r['mean'])} paired {_signed(paired.get('mean'))} "
            f"({_signed(paired.get('low'))}..{_signed(paired.get('high'))})"
        )
    frozen = res.get("frozen")
    if frozen:
        lines.append(f"Frozen picks at {frozen['at']} out of {frozen['tried']} books: " + (", ".join(frozen["picks"]) or "none"))
    else:
        lines.append("Provisional leaders (not frozen): " + (", ".join(res.get("leaders") or []) or "none with 30 trades"))
    lines.append(f"Confirm week: {res.get('confirm_coins', 0)} finished coins")
    return lines


def _quote_lines(report):
    cal = report.get("quotes") or {}
    data = cal.get("summary") or {}
    lines = ["", "Jupiter quotes beside paper fills (gap > 0 means the real route was worse)"]
    if not data:
        lines.append(f"  {cal.get('why', 'no quote log yet')}")
        return lines
    cov = data.get("coverage")
    lines.append(f"  quotes {data.get('n', 0)} for {data.get('fills', 0)} fills, coverage {_pct1(cov)} (target 95%)")
    for side in ("buy", "sell"):
        s = (data.get("sides") or {}).get(side) or {}
        n = s.get("n") or 0
        lines.append(
            f"  {side}: ok {s.get('ok', 0)} of {n}, median gap {_pct1(s.get('median_gap'))}, "
            f"p90 {_pct1(s.get('p90_gap'))}, no route {_pct1((s.get('no_route') or 0) / n if n else None)}"
        )
    lines.append(f"  {cal.get('why', '')}")
    return lines


def _signed(value):
    if value is None:
        return "-"
    return f"{'+' if value >= 0 else '-'}${abs(value):.3f}"


def _pct1(value):
    if value is None:
        return "-"
    return f"{value:.1%}"


def _money(value):
    if value is None:
        return "-"
    return f"${value:.2f}"


def _pct(value):
    if value is None:
        return "-"
    return f"{value:.0%}"


def _table(rows):
    if not rows:
        return ["  none yet"]
    return [
        f"  {row['name']}: n={row['n']} mean={_money(row['mean'])} win={_pct(row['win_rate'])} "
        f"2x before stop={_pct1(row.get('rate_2x'))}"
        for row in rows
    ]


def collect_loop(store):
    while True:
        with LOCK:
            fetch_desk(store)
            price_due(store)
        time.sleep(60)


def report_loop(store):
    while True:
        try:
            with REPORT_LOCK:
                _REPORT["report"] = build_report(store)
                _REPORT["at"] = time.time()
        except Exception as exc:
            print("report build failed:", type(exc).__name__, str(exc)[:120])
        time.sleep(REPORT_TTL_S)


def serve():
    store = Store(DB_PATH)
    reader = Store(DB_PATH)
    threading.Thread(target=collect_loop, args=(store,), daemon=True).start()
    threading.Thread(target=report_loop, args=(reader,), daemon=True).start()
    key = env("LAB_KEY")
    port = int(env("PORT", "8090") or "8090")
    # The cookie holds a hash of the key, not the key, and changes when LAB_KEY changes.
    session = hashlib.sha256(("lab-session:" + key).encode()).hexdigest() if key else ""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _ok_key(self):
            if not key:
                return False
            if hmac.compare_digest(self.headers.get("X-Lab-Key", ""), key):
                return True
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            for part in query.split("&"):
                if part.startswith("key=") and hmac.compare_digest(
                        urllib.parse.unquote_plus(part.split("=", 1)[1]), key):
                    return True
            for part in (self.headers.get("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == "lab_session" and hmac.compare_digest(value, session):
                    return True
            return False

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/login":
                self._send(404, "not found", "text/plain")
                return
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            sent = (form.get("key") or [""])[0]
            if not key or not hmac.compare_digest(sent, key):
                time.sleep(1)
                self._send(401, _login_page("Wrong key."), "text/html; charset=utf-8")
                return
            self.send_response(303)
            self.send_header(
                "Set-Cookie",
                f"lab_session={session}; Max-Age={30 * 86400}; Path=/; HttpOnly; Secure; SameSite=Strict",
            )
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, code, body, content):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, "ok", "text/plain")
                return
            if not self._ok_key():
                if path == "/api/report":
                    self._send(401, "lab key required", "text/plain")
                else:
                    note = "" if key else "LAB_KEY is not set on this service, so every key is refused."
                    self._send(401, _login_page(note), "text/html; charset=utf-8")
                return
            with REPORT_LOCK:
                report = cached_report(reader)
            if path == "/api/report":
                self._send(200, json.dumps(report), "application/json")
                return
            self._send(200, _page(report), "text/html; charset=utf-8")

    print(f"Paper Scanner Lab on http://0.0.0.0:{port}")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
        server.shutdown()


def _login_page(note=""):
    note_html = f'<p class="bad">{note}</p>' if note else ""
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Scanner Lab</title>
<style>
  body {{ margin: 0; background: #10140f; color: #e7f0df; font: 15px/1.45 ui-sans-serif, system-ui, sans-serif; }}
  main {{ max-width: 360px; margin: 18vh auto 0; padding: 0 18px; }}
  h1 {{ font-size: 22px; margin: 0 0 8px; }}
  p {{ color: #9aab90; }}
  .bad {{ color: #ff8a7a; }}
  input, button {{ width: 100%; box-sizing: border-box; font: inherit; padding: 10px 12px; border-radius: 10px; }}
  input {{ background: #181e16; color: #e7f0df; border: 1px solid #2c3826; margin: 8px 0 12px; }}
  button {{ background: #8fd16a; color: #10140f; border: 0; font-weight: 600; cursor: pointer; }}
</style>
<main>
  <h1>Paper Scanner Lab</h1>
  <p>Read-only. Enter the lab key (LAB_KEY on the scanner-lab service).</p>
  {note_html}
  <form method="post" action="/login">
    <input type="password" name="key" autocomplete="current-password" autofocus required>
    <button type="submit">Open the lab</button>
  </form>
</main>
"""


def _page(report):
    text = format_report(report).replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Paper Scanner Lab</title>
<style>
  body {{ margin: 0; background: #10140f; color: #e7f0df; font: 15px/1.45 ui-monospace, Consolas, monospace; }}
  main {{ max-width: 920px; margin: 0 auto; padding: 28px 18px 48px; }}
  h1 {{ font: 600 22px/1.2 ui-sans-serif, system-ui, sans-serif; margin: 0 0 8px; }}
  p {{ color: #9aab90; }}
  pre {{ white-space: pre-wrap; background: #181e16; border: 1px solid #2c3826; border-radius: 12px; padding: 16px; }}
</style>
<main>
  <h1>Paper Scanner Lab</h1>
  <p>Read-only. This page does not trade and does not change the desk.</p>
  <pre>{text}</pre>
</main>
"""


def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    store = Store(DB_PATH)
    if cmd == "collect":
        collect_loop(store)
    elif cmd == "report":
        with LOCK:
            fetch_desk(store)
        print(format_report(build_report(store)))
    elif cmd == "serve":
        serve()
    else:
        raise SystemExit("use serve, collect, or report")


if __name__ == "__main__":
    main()
