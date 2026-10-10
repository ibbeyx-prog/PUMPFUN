"""
Railway entrypoint: runs the paper-trading agent in the background and serves
a JSON API + the React dashboard from one process.

Env vars:
  HELIUS_API_KEY   required
  DASH_TOKEN       password for the dashboard/API (strongly recommended)
  DATA_DIR         where state is stored (mount a Railway volume, e.g. /data)
  RESCORE_HOURS    how often to re-rank wallets (default 24)
  PORT             set by Railway
"""
import asyncio, csv, json, os, time

import aiohttp
from aiohttp import web

import copytrader as ct
import reports
import scanner
import tune

TOKEN = os.getenv("DASH_TOKEN", "")
RESCORE = float(os.getenv("RESCORE_HOURS", "24")) * 3600
STATUS = {"phase": "starting", "wallets": 0, "last_score": 0, "started": time.time()}
ENG = None


# ───────────── background agent ─────────────
async def guard(name, fn):
    """Restart a background coroutine if it ever crashes."""
    while True:
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"{name} crashed: {e!r} - restarting in 5s")
            await asyncio.sleep(5)


def wallets_stale():
    if not os.path.exists(ct.WALLETS):
        return True
    return time.time() - os.path.getmtime(ct.WALLETS) > RESCORE


async def supervisor(app):
    global ENG
    ENG = ct.Paper()
    session = aiohttp.ClientSession()
    asyncio.create_task(guard("manage", lambda: ENG.manage(session)))
    asyncio.create_task(guard("scan", lambda: scanner.scan_loop(ENG, session, STATUS)))
    asyncio.create_task(guard("reports", _reports))
    # Wallet copy stays available, but entries come from the scanner.
    if os.path.exists(ct.WALLETS):
        wallets = [m["wallet"] for m in json.load(open(ct.WALLETS)) if m.get("wallet")]
        STATUS["wallets"] = len(wallets)
        if wallets:
            asyncio.create_task(guard("watch", lambda w=wallets: ct.watch(ENG, session, w)))


async def _reports():
    while True:
        try:
            reports.roll()
        except Exception as e:
            print("report failed:", e)
        await asyncio.sleep(300)


async def start_bg(app):
    app["task"] = asyncio.create_task(supervisor(app))


# ───────────── API ─────────────
@web.middleware
async def auth(request, handler):
    if request.path.startswith("/api/") and TOKEN:
        sent = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if sent != TOKEN:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


def read_trades():
    if not os.path.exists(ct.TRADES):
        return []
    with open(ct.TRADES, newline="") as f:
        return list(csv.DictReader(f))


def _source_count(label):
    return len([s for s in (label or "").split("+") if s])


def lessons(rows):
    """What the closed paper trades actually did, grouped by how many sites agreed."""
    closed = [r for r in rows if r.get("event") == "CLOSED"]
    buckets = {}
    stops = 0
    for r in closed:
        n = max(1, _source_count(r.get("wallet")))
        buckets.setdefault(n, []).append(float(r["sol_pnl"]))
        if "stop-loss" in (r.get("note") or ""):
            stops += 1

    def pack(xs):
        if not xs:
            return None
        return {"n": len(xs), "win_rate": sum(1 for x in xs if x > 0) / len(xs),
                "pnl": round(sum(xs), 4)}

    n, wins = len(closed), sum(1 for r in closed if float(r["sol_pnl"]) > 0)
    text = "Not enough closed trades to suggest yet."
    if n >= 5:
        bits = [f"{wins}/{n} closes won"]
        three = pack(buckets.get(3, []))
        if three:
            bits.append(f"3-source pnl {three['pnl']:+.3f} SOL")
        if stops / n >= 0.5:
            bits.append(f"{stops} stopped out")
        one = pack(buckets.get(1, []))
        if one and one["n"] >= 3 and one["win_rate"] < 0.4:
            bits.append("1-source entries have been weak")
        text = ". ".join(bits) + "."
    return {
        "closed": n,
        "win_rate": (wins / n) if n else None,
        "stops": stops,
        "by_sources": {str(k): pack(v) for k, v in buckets.items()},
        "text": text,
    }


def advise_open(p, lesson):
    x, age = p.get("x") or 0, p.get("age_min") or 0
    nsrc = max(1, _source_count(p.get("wallet")))
    if lesson["closed"] < 5:
        return {"label": "Hold", "text": "Need a few more closes before a stronger call."}
    if x >= 2:
        return {"label": "Sell", "text": "At 2x. The trades that paid were sold on the ladder."}
    if x < 0.75 and age >= 8:
        return {"label": "Cut", "text": "Under 0.75x after several minutes. Most losers were stopped here."}
    if nsrc < 3 and x < 1 and age >= 12:
        return {"label": "Cut", "text": f"Only {nsrc} source(s) and still under entry. That mix has mostly lost."}
    if x >= 1:
        return {"label": "Hold", "text": "Above entry. Let it try for 2x."}
    if age < 8:
        return {"label": "Wait", "text": "Just opened. Too early to cut."}
    return {"label": "Hold", "text": "No exit rule hit yet."}


def advise_candidate(c, lesson):
    nsrc = len(c.get("sources") or [])
    decision = c.get("decision")
    if lesson["closed"] < 5:
        label = {"enter": "Take", "skip": "Skip"}.get(decision, "Wait")
        return {"label": label, "text": "Not enough closed trades to override the score."}
    bucket = (lesson.get("by_sources") or {}).get(str(max(nsrc, 1))) or {}
    if decision == "skip":
        return {"label": "Skip", "text": c.get("note") or "Filters say no."}
    if decision == "enter" and nsrc >= 3:
        extra = f" History {bucket['pnl']:+.3f} SOL over {bucket['n']}." if bucket.get("n") else ""
        return {"label": "Take", "text": "Three sources agree." + extra}
    if decision == "enter" and nsrc <= 1:
        return {"label": "Pass", "text": "One source only. Those entries have mostly stopped out."}
    if decision == "enter":
        wr, count = bucket.get("win_rate"), bucket.get("n") or 0
        if wr is not None and count >= 3 and wr < 0.35:
            return {"label": "Pass", "text": f"{nsrc}-source closes won {wr:.0%} of {count}. Wait for a third source."}
        return {"label": "Small", "text": f"{nsrc} sources. History is mixed, so don't add size."}
    return {"label": "Wait", "text": "Not a clean entry yet."}


async def api_summary(request):
    rows = read_trades()
    closed = [r for r in rows if r["event"] == "CLOSED"]
    pnls = [float(r["sol_pnl"]) for r in closed]
    cum, run = [], 0.0
    for p in pnls:
        run += p
        cum.append(round(run, 4))
    lesson = lessons(rows)
    open_pos = []
    for mint, p in (ENG.pos if ENG else {}).items():
        item = {"mint": mint, "symbol": p.get("symbol") or "",
                "wallet": p["wallet"], "entry": p["entry"],
                "left": p["left"], "tier": p["tier"],
                "x": p.get("last_x"), "age_min": (time.time() - p["t0"]) / 60,
                "pnl": p["pnl"]}
        item["advice"] = advise_open(item, lesson)
        open_pos.append(item)
    return web.json_response({
        "status": STATUS,
        "paper_mode": True,
        "total_pnl": round(sum(pnls), 4),
        "closed": len(closed),
        "win_rate": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
        "skipped": sum(1 for r in rows if r["event"] == "SKIP"),
        "cum_pnl": cum,
        "open": open_pos,
        "config": {k: ct.CFG[k] for k in ("size_sol", "ladder", "stop_loss_pct",
                                           "max_open_positions", "max_chase_pct",
                                           "entry_score")},
        "scan": {"at": scanner.STATE["scanned_at"], "sources": scanner.STATE["sources"]},
        "lesson": lesson,
        "agent": tune.public(),
        "reports": reports.public(),
    })


async def api_trades(request):
    limit = int(request.query.get("limit", 200))
    return web.json_response(read_trades()[-limit:][::-1])


async def api_candidates(request):
    lesson = lessons(read_trades())
    candidates = []
    for c in scanner.STATE["candidates"]:
        item = dict(c)
        item["advice"] = advise_candidate(item, lesson)
        candidates.append(item)
    return web.json_response({
        "candidates": candidates,
        "sources": scanner.STATE["sources"],
        "scanned_at": scanner.STATE["scanned_at"],
        "lesson": lesson,
    })


async def api_wallets(request):
    if not os.path.exists(ct.WALLETS):
        return web.json_response([])
    return web.json_response(json.load(open(ct.WALLETS)))


async def health(request):
    return web.json_response({"ok": True})


# ───────────── static dashboard ─────────────
DIST = os.path.join(os.path.dirname(__file__), "dashboard", "dist")


async def index(request):
    p = os.path.join(DIST, "index.html")
    if os.path.exists(p):
        return web.FileResponse(p)
    return web.Response(text="Dashboard not built. API is at /api/summary", status=200)


async def favicon(request):
    return web.Response(status=204)


def make_app():
    app = web.Application(middlewares=[auth])
    app.add_routes([
        web.get("/health", health),
        web.get("/api/summary", api_summary),
        web.get("/api/trades", api_trades),
        web.get("/api/wallets", api_wallets),
        web.get("/api/candidates", api_candidates),
        web.get("/", index),
        web.get("/favicon.ico", favicon),
    ])
    if os.path.isdir(os.path.join(DIST, "assets")):
        app.router.add_static("/assets", os.path.join(DIST, "assets"))
    app.on_startup.append(start_bg)
    return app


if __name__ == "__main__":
    if "PASTE_YOUR" in ct.KEY:
        raise SystemExit("Set HELIUS_API_KEY")
    if not TOKEN:
        print("WARNING: DASH_TOKEN not set - dashboard/API is open to anyone with the URL")
    web.run_app(make_app(), port=int(os.getenv("PORT", "8080")))
