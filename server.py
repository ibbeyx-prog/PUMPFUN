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
import chat
import eye
import live
import reports
import scanner
import skills
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
    live.halt("paper mode")
    session = aiohttp.ClientSession()
    asyncio.create_task(guard("manage", lambda: ENG.manage(session)))
    asyncio.create_task(guard("scan", lambda: scanner.scan_loop(ENG, session, STATUS)))
    asyncio.create_task(guard("reports", _reports))
    asyncio.create_task(guard("eye", lambda: _eye(session)))
    # Wallet copy stays available, but entries come from the scanner.
    if os.path.exists(ct.WALLETS):
        wallets = [m["wallet"] for m in json.load(open(ct.WALLETS)) if m.get("wallet")]
        STATUS["wallets"] = len(wallets)
        if wallets:
            asyncio.create_task(guard("watch", lambda w=wallets: ct.watch(ENG, session, w)))


async def _eye(session):
    retried = False
    while True:
        wait = 600
        try:
            await eye.research()
            data = await eye.grow(session)
            if not retried and "has not posted names" in (data.get("market") or ""):
                retried = True
                wait = 50
            await eye.review()
        except Exception as e:
            print("eye failed:", type(e).__name__, e)
        await asyncio.sleep(wait)


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
    pnl = round(sum(pnls), 4)
    sol_px = scanner.STATE.get("sol_usd")
    if not sol_px or time.time() - (scanner.STATE.get("sol_usd_at") or 0) > 90:
        try:
            async with aiohttp.ClientSession() as session:
                sol_px = await scanner.sol_usd(session) or sol_px
        except Exception:
            pass
    tips = eye.improvements(rows)
    open_pos = []
    for mint, p in (ENG.pos if ENG else {}).items():
        item = {"mint": mint, "symbol": p.get("symbol") or "",
                "wallet": p["wallet"], "entry": p["entry"],
                "left": p["left"], "tier": p["tier"],
                "x": p.get("last_x"), "age_min": (time.time() - p["t0"]) / 60,
                "pnl": p["pnl"]}
        item["advice"] = advise_open(item, lesson)
        item["eye"] = eye.for_open(item, tips)
        open_pos.append(item)
    return web.json_response({
        "status": STATUS,
        "paper_mode": True,
        "total_pnl": pnl,
        "sol_usd": None if not sol_px else round(float(sol_px), 2),
        "total_pnl_usd": None if not sol_px else round(pnl * float(sol_px), 2),
        "closed": len(closed),
        "win_rate": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
        "skipped": sum(1 for r in rows if r["event"] == "SKIP"),
        "cum_pnl": cum,
        "open": open_pos,
        "config": {k: ct.CFG[k] for k in ("trade_usd", "reserve_usd", "budget_usd",
                                           "one_trade_per_coin", "ladder", "stop_loss_pct",
                                           "max_open_positions", "max_chase_pct",
                                           "entry_score")},
        "budget": ENG.budget_view() if ENG else {
            "sol_usd": None, "start_usd": ct.CFG["budget_usd"], "equity_usd": ct.CFG["budget_usd"],
            "realized_usd": 0, "deployed_usd": 0,
            "available_usd": ct.CFG["budget_usd"] - ct.CFG["reserve_usd"],
            "reserve_usd": ct.CFG["reserve_usd"], "trade_usd": ct.CFG["trade_usd"],
        },
        "live": live.public(),
        "scan": {"at": scanner.STATE["scanned_at"], "sources": scanner.STATE["sources"]},
        "lesson": lesson,
        "agent": tune.public(),
        "skills": skills.public(),
        "reports": reports.public(),
    })


async def api_eye(request):
    return web.json_response(eye.public())


async def api_trades(request):
    limit = int(request.query.get("limit", 200))
    rows = read_trades()
    tips = eye.improvements(rows)
    out = []
    for r in rows[-limit:][::-1]:
        item = dict(r)
        tip = eye.for_trade(item, tips)
        if tip:
            item["eye"] = tip
        out.append(item)
    return web.json_response(out)


async def api_candidates(request):
    rows = read_trades()
    lesson = lessons(rows)
    tips = eye.improvements(rows)
    candidates = []
    for c in scanner.STATE["candidates"]:
        item = dict(c)
        item["advice"] = advise_candidate(item, lesson)
        item["eye"] = eye.for_candidate(item, tips)
        candidates.append(item)
    return web.json_response({
        "candidates": candidates,
        "sources": scanner.STATE["sources"],
        "scanned_at": scanner.STATE["scanned_at"],
        "lesson": lesson,
    })


def chat_context():
    rows = read_trades()
    lesson = lessons(rows)
    closed = []
    for r in rows:
        if r.get("event") != "CLOSED":
            continue
        sym = ""
        for b in rows:
            if b.get("event") == "BUY" and b.get("mint") == r.get("mint"):
                sym = (b.get("note") or "").split(" size")[0].strip()
                break
        closed.append({"symbol": sym, "mint": r.get("mint"), "x": float(r.get("x") or 0),
                       "pnl": float(r.get("sol_pnl") or 0), "note": r.get("note") or ""})
    open_pos = []
    for mint, p in (ENG.pos if ENG else {}).items():
        item = {"mint": mint, "symbol": p.get("symbol") or "", "wallet": p.get("wallet"),
                "x": p.get("last_x"), "pnl": p.get("pnl"), "age_min": (time.time() - p["t0"]) / 60}
        item["advice"] = advise_open(item, lesson)
        open_pos.append(item)
    agent = tune.public()
    reps = reports.public()
    latest = (reps.get("reports") or [None])[0]
    pnls = [c["pnl"] for c in closed]
    return {
        "pnl": round(sum(pnls), 4) if pnls else 0,
        "closed": len(closed),
        "win_rate": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
        "lesson": lesson.get("text"),
        "phase": STATUS.get("phase"),
        "open": open_pos,
        "closed_rows": closed[-12:],
        "cands": [dict(c, advice=advise_candidate(c, lesson)) for c in (scanner.STATE.get("candidates") or [])],
        "changes": agent.get("changes") or [],
        "rules": agent.get("values") or {},
        "report": latest,
        "next_report": reps.get("next_at"),
        "skills_text": skills.summary(),
    }


async def api_chat_get(request):
    return web.json_response({"messages": chat.history()})


async def api_chat_post(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    message = str((body or {}).get("message") or "").strip()
    if not message:
        return web.json_response({"error": "empty"}, status=400)
    if len(message) > 500:
        message = message[:500]
    reply = chat.answer(message, chat_context())
    chat.add("user", message)
    chat.add("agent", reply)
    return web.json_response({"reply": reply, "messages": chat.history()})


async def api_wallets(request):
    if not os.path.exists(ct.WALLETS):
        return web.json_response([])
    return web.json_response(json.load(open(ct.WALLETS)))


SOL_MINT = "So11111111111111111111111111111111111111112"


async def api_phantom_get(request):
    return web.json_response(live.public())


async def api_phantom_post(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    ok, why = live.set_phantom(
        (body or {}).get("address") or "",
        bool((body or {}).get("trade")),
        (body or {}).get("pin") or "",
    )
    if not ok:
        return web.json_response({"error": why, **live.public()}, status=400)
    return web.json_response(live.public())


async def api_phantom_lock(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    ok, why = live.set_lock((body or {}).get("pin") or "", (body or {}).get("old") or "")
    if not ok:
        return web.json_response({"error": why, **live.public()}, status=400)
    return web.json_response(live.public())


async def api_phantom_swap(request):
    """Build a Jupiter buy for the connected address. The browser asks Phantom to sign it."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    ok, why = live.check_lock((body or {}).get("pin") or "")
    if not ok:
        return web.json_response({"error": why, **live.public()}, status=401)
    order = live.pending_order()
    if not order or str(order.get("id")) != str((body or {}).get("id") or ""):
        return web.json_response({"error": "no pending buy"}, status=404)
    state = live.public()
    if not state.get("wallet_trade") or not state.get("phantom"):
        return web.json_response({"error": "wallet trading is off"}, status=400)
    px = live.sol_price() or scanner.STATE.get("sol_usd")
    if not px:
        return web.json_response({"error": "no SOL price"}, status=400)
    lamports = int(float(order["usd"]) / float(px) * 1_000_000_000)
    if lamports < 1_000_000:
        live.finish_order(order["id"], error="buy is under 0.001 SOL")
        return web.json_response({"error": "buy is under 0.001 SOL"}, status=400)
    quote_url = (
        "https://api.jup.ag/swap/v1/quote"
        f"?inputMint={SOL_MINT}&outputMint={order['mint']}"
        f"&amount={lamports}&slippageBps=300"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                quote = await resp.json(content_type=None)
                if resp.status != 200:
                    raise RuntimeError("quote failed")
            async with session.post(
                "https://api.jup.ag/swap/v1/swap",
                json={"quoteResponse": quote, "userPublicKey": state["phantom"], "wrapAndUnwrapSol": True},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                swap = await resp.json(content_type=None)
                if resp.status != 200 or not swap.get("swapTransaction"):
                    raise RuntimeError("swap failed")
    except Exception:
        live.finish_order(order["id"], error="Jupiter has no route for this token")
        return web.json_response({"error": "Jupiter has no route for this token"}, status=502)
    return web.json_response({
        "id": order["id"],
        "symbol": order.get("symbol") or "",
        "usd": order.get("usd"),
        "transaction": swap["swapTransaction"],
    })


async def api_phantom_done(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    live.finish_order(
        (body or {}).get("id"),
        signature=(body or {}).get("signature") or "",
        error=(body or {}).get("error") or "",
    )
    return web.json_response(live.public())


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
        web.get("/api/eye", api_eye),
        web.get("/api/chat", api_chat_get),
        web.post("/api/chat", api_chat_post),
        web.get("/api/phantom", api_phantom_get),
        web.post("/api/phantom", api_phantom_post),
        web.post("/api/phantom/lock", api_phantom_lock),
        web.post("/api/phantom/swap", api_phantom_swap),
        web.post("/api/phantom/done", api_phantom_done),
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
