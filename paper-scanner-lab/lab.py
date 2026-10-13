"""
Paper Scanner Lab. Read-only sidecar.

It reads the desk API and writes only its own sqlite file. It does not trade
and it does not open the desk's ledger, bank, config, or .env.
"""
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
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
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
               sources, mcap, liq, change_5m, price_sol, age_min, rug_label)
               values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["scanned_at"], row["recorded_at"], row["mint"], row["symbol"], row["score"],
                row["decision"], row["note"], json.dumps(row["sources"]), row["mcap"], row["liq"],
                row["change_5m"], row["price_sol"], row["age_min"], row["rug_label"],
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
               sources, mcap, liq, change_5m, age_min, rug_label)
               values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["mint"], row["symbol"], now, now + engine.TRACK_S, row["score"], row["decision"],
                row["note"], json.dumps(row["sources"]), row["mcap"], row["liq"], row["change_5m"],
                row["age_min"], row["rug_label"],
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

    def due_episodes(self, now, limit=20):
        return self.db.execute(
            """select id, mint from episodes
               where done = 0 and track_until > ?
               order by started_at asc limit ?""",
            (now - 60, limit),
        ).fetchall()

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
                "path": path,
                "done": bool(row["done"]),
                "forward": None,
            }
            if path:
                entry = next((px for at, px in path if at >= row["started_at"] + engine.ENTRY_DELAY_S), None)
                if entry:
                    end_px = path[-1][1]
                    item["forward"] = engine.round_trip(entry, end_px, engine.SIZE_USD, row["liq"])
            out.append(item)
        return out

    def trades(self):
        return [dict(row) for row in self.db.execute("select * from desk_trades order by id")]

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
        print(f"recorded scan, new episodes {added}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("desk read failed: HTTP 401. The desk rejected DASH_TOKEN.")
        else:
            print(f"desk read failed: HTTP {exc.code}")
    except Exception as exc:
        print("desk read failed:", type(exc).__name__)


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
    try:
        prices = _token_prices([row["mint"] for row in rows])
    except Exception as exc:
        print("price read failed:", type(exc).__name__)
        return
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


def readiness(store, books):
    """The desk refuses live trading until this object says ready."""
    row = next((book for book in books if book.get("id") == "desk-ladder"), None) or {}
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
        "book": "desk-ladder",
        "closes": n,
        "span_days": round(span, 2),
        "ci_low": low,
        "random_percentile": pct,
        "ready": ready,
    }


def build_report(store):
    episodes = store.episodes_for_report()
    done = [ep for ep in episodes if ep["done"] or ep["path"]]
    books = engine.run_books(done)
    later = {}
    for ep in episodes:
        first = next((px for _, px in ep["path"] if px), 0)
        if first:
            later[ep["mint"]] = max(px for _, px in ep["path"]) / first
    losses = engine.desk_loss_report(store.trades(), later)
    counts = store.counts()
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "counts": counts,
        "sample": engine.sample_label(counts["episodes"]),
        "outcomes": engine.outcome_tables(done),
        "books": books,
        "tickets": engine.ticket_books(done),
        "baselines": engine.baselines(done),
        "readiness": readiness(store, books),
        "desk_losses": losses,
        "hypotheses": hypotheses(books, losses, counts),
        "fills": {
            "size_usd": engine.SIZE_USD,
            "fee_per_side": engine.FEE,
            "flat_usd": engine.FLAT_USD,
            "entry_delay_s": engine.ENTRY_DELAY_S,
            "track_hours": 4,
        },
    }
    return report


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
    lines = [
        f"Paper Scanner Lab  {report['generated_at']}",
        f"Sample: {report['sample']}  scan rows {report['counts']['hits']}  coins {report['counts']['episodes']}  finished {report['counts']['done']}",
        "Fills are harsher than the desk: slippage grows with size/liquidity, 1% fee per side, $0.20 per transaction, 45s entry delay, vanished tokens ~90% loss.",
        "",
        "Outcomes by decision",
    ]
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
    lines.append("Shadow books")
    for book in report["books"]:
        ci = book["ci"] or {}
        pct = book["random_percentile"]
        lines.append(
            f"{book['name']}: n={book['n']} total={_money(book['total'])} "
            f"mean={_money(book['mean'])} win={_pct(book['win_rate'])} "
            f"CI={_money(ci.get('low'))}..{_money(ci.get('high'))} "
            f"{book['verdict']}"
            + (f"  random percentile {pct:.0f}" if pct is not None else "")
        )
    lines.append("")
    lines.append("Ticket size, desk ladder")
    for book in report.get("tickets") or []:
        lines.append(
            f"{book['name']}: n={book['n']} total={_money(book['total'])} "
            f"mean={_money(book['mean'])} win={_pct(book['win_rate'])} {book['verdict']}"
        )
    lines.append("")
    lines.append("Baselines")
    for book in report.get("baselines") or []:
        lines.append(f"{book['name']}: n={book['n']} total={_money(book['total'])} mean={_money(book['mean'])}")
    gate = report.get("readiness") or {}
    lines.append("")
    lines.append(
        "Live gate: "
        + ("open" if gate.get("ready") else "closed")
        + f"  desk-ladder n={gate.get('closes')}  span {gate.get('span_days')}d"
    )
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
        f"  {row['name']}: n={row['n']} mean={_money(row['mean'])} win={_pct(row['win_rate'])}"
        for row in rows
    ]


def collect_loop(store):
    while True:
        with LOCK:
            fetch_desk(store)
            price_due(store)
        time.sleep(60)


def serve():
    store = Store(DB_PATH)
    threading.Thread(target=collect_loop, args=(store,), daemon=True).start()
    key = env("LAB_KEY")
    port = int(env("PORT", "8090") or "8090")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _ok_key(self):
            if not key:
                return False
            sent = self.headers.get("X-Lab-Key", "")
            if sent == key:
                return True
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            for part in query.split("&"):
                if part.startswith("key=") and urllib.parse.unquote(part.split("=", 1)[1]) == key:
                    return True
            return False

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
                self._send(401, "lab key required", "text/plain")
                return
            with LOCK:
                report = build_report(store)
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
