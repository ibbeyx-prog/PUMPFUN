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
import scanner

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
    # Wallet copy stays available, but entries come from the scanner.
    if os.path.exists(ct.WALLETS):
        wallets = [m["wallet"] for m in json.load(open(ct.WALLETS)) if m.get("wallet")]
        STATUS["wallets"] = len(wallets)
        if wallets:
            asyncio.create_task(guard("watch", lambda w=wallets: ct.watch(ENG, session, w)))


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


async def api_summary(request):
    rows = read_trades()
    closed = [r for r in rows if r["event"] == "CLOSED"]
    pnls = [float(r["sol_pnl"]) for r in closed]
    cum, run = [], 0.0
    for p in pnls:
        run += p
        cum.append(round(run, 4))
    open_pos = []
    for mint, p in (ENG.pos if ENG else {}).items():
        open_pos.append({"mint": mint, "symbol": p.get("symbol") or "",
                         "wallet": p["wallet"], "entry": p["entry"],
                         "left": p["left"], "tier": p["tier"],
                         "x": p.get("last_x"), "age_min": (time.time() - p["t0"]) / 60,
                         "pnl": p["pnl"]})
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
    })


async def api_trades(request):
    limit = int(request.query.get("limit", 200))
    return web.json_response(read_trades()[-limit:][::-1])


async def api_candidates(request):
    return web.json_response({
        "candidates": scanner.STATE["candidates"],
        "sources": scanner.STATE["sources"],
        "scanned_at": scanner.STATE["scanned_at"],
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
