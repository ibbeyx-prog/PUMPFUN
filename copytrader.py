"""
pump.fun wallet copy-trader (PAPER MODE ONLY)

  python copytrader.py score   -> find + rank profitable wallets -> wallets.json
  python copytrader.py discover -> debug: show winning tokens + candidate wallets
  python copytrader.py run     -> watch ranked wallets, paper-copy their buys,
                                  exit on a 2X / 3.5X / 5X ladder

No real trades are placed. Results are written to trades.csv.
"""
import asyncio, csv, json, os, statistics, sys, time
from datetime import datetime
from collections import Counter, defaultdict

import aiohttp

CFG = json.load(open("config.json"))
KEY = os.getenv("HELIUS_API_KEY") or CFG["helius_api_key"]
DATA = os.getenv("DATA_DIR", ".")            # on Railway: mount a volume here
os.makedirs(DATA, exist_ok=True)
WALLETS = os.path.join(DATA, "wallets.json")
TRADES = os.path.join(DATA, "trades.csv")
STATE = os.path.join(DATA, "state.json")
HELIUS = "https://api.helius.xyz"
WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={KEY}"
WSOL = "So11111111111111111111111111111111111111112"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
GT_HEADERS = {"Accept": "application/json;version=20230302"}
SEM = asyncio.Semaphore(5)


# ───────────────────────── Helius helpers ─────────────────────────
async def fetch_txs(s, addr, pages):
    out, before = [], None
    for _ in range(pages):
        url = f"{HELIUS}/v0/addresses/{addr}/transactions?api-key={KEY}&limit=100"
        if before:
            url += f"&before={before}"
        batch = None
        for attempt in range(4):
            async with SEM:
                async with s.get(url) as r:
                    if r.status == 429:           # rate limited -> back off, retry
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    if r.status == 200:
                        batch = await r.json()
                    else:
                        body = (await r.text())[:120]
                        print(f"  Helius HTTP {r.status}: {body}")
                    break
        if not batch:
            break
        out += batch
        before = batch[-1]["signature"]
        if len(batch) < 100:
            break
    return out


async def parse_sig(s, sig, tries=5):
    """Fetch an enhanced-parsed tx; it can take a second to be indexed."""
    for _ in range(tries):
        async with SEM:
            async with s.post(f"{HELIUS}/v0/transactions?api-key={KEY}",
                              json={"transactions": [sig]}) as r:
                if r.status == 200:
                    data = await r.json()
                    if data:
                        return data[0]
        await asyncio.sleep(1)
    return None


def parse_swap(tx, w):
    """Return (mint, side, token_amount, sol_delta) for wallet w, or None."""
    if not tx or tx.get("transactionError"):
        return None
    sol = sum(a["nativeBalanceChange"] for a in tx.get("accountData", [])
              if a["account"] == w) / 1e9
    got = sent = 0.0
    mint = None
    for t in tx.get("tokenTransfers", []):
        if t["mint"] == WSOL:
            continue
        if t.get("toUserAccount") == w:
            got += t["tokenAmount"]; mint = t["mint"]
        elif t.get("fromUserAccount") == w:
            sent += t["tokenAmount"]; mint = t["mint"]
    if not mint:
        return None
    if got > sent and sol < 0:
        return mint, "buy", got, -sol
    if sent > got and sol > 0:
        return mint, "sell", sent, sol
    return None


def _pair_liq(p):
    try:
        return float((p.get("liquidity") or {}).get("usd") or 0)
    except (TypeError, ValueError):
        return 0.0


async def price_sol(s, mint):
    """SOL per token from the deepest WSOL pair whose USD price implies a sane SOL price.

    Dust pools sometimes print a price thousands of times off the real market. Those
    fail the implied-SOL check and cannot open or stop out a paper position.
    """
    try:
        async with s.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}") as r:
            pairs = (await r.json()).get("pairs") or []
        good = []
        for p in pairs:
            if (p.get("quoteToken") or {}).get("address") != WSOL:
                continue
            try:
                native = float(p.get("priceNative") or 0)
                usd = float(p.get("priceUsd") or 0)
            except (TypeError, ValueError):
                continue
            if native <= 0 or usd <= 0:
                continue
            implied_sol = usd / native
            if not (15 <= implied_sol <= 1000):
                continue
            good.append((_pair_liq(p), native))
        if not good:
            return None
        liquid = [g for g in good if g[0] >= 500]
        return max(liquid or good)[1]
    except Exception:
        return None


# ───────────────────────── Discovery + scoring ─────────────────────────
async def get_json(s, url, headers=None):
    for attempt in range(3):
        try:
            async with s.get(url, headers=headers) as r:
                if r.status == 429:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if r.status != 200:
                    print(f"  HTTP {r.status} for {url[:90]}")
                    return None
                return await r.json()
        except Exception as e:
            print("  request failed:", e)
            await asyncio.sleep(1)
    return None


def _age_ok(ts, max_age_sec):
    return ts and (time.time() - ts) <= max_age_sec


async def winning_tokens(s):
    """Recent pump.fun tokens (mint ends in 'pump') that already pumped hard.
    Sources: GeckoTerminal pools, then DexScreener search, plus seed_tokens."""
    min_gain = CFG["discover_min_gain_pct"]
    max_age = CFG["discover_max_age_days"] * 86400
    found = {}

    urls = ([f"{GT}/trending_pools?duration=24h&page={p}" for p in (1, 2, 3)]
            + [f"{GT}/new_pools?page={p}" for p in (1, 2, 3)]
            + [f"{GT}/dexes/pumpswap/pools?page={p}" for p in (1, 2, 3)])
    for url in urls:
        data = await get_json(s, url, GT_HEADERS)
        for pool in (data or {}).get("data", []):
            try:
                a = pool["attributes"]
                mint = pool["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
                gain = float((a.get("price_change_percentage") or {}).get("h24") or 0)
                liq = float(a.get("reserve_in_usd") or 0)
                created = datetime.fromisoformat(
                    a["pool_created_at"].replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if mint.endswith("pump") and gain >= min_gain and liq >= 5000 \
                    and _age_ok(created, max_age):
                found[mint] = max(gain, found.get(mint, 0))
        await asyncio.sleep(0.5)
    print(f"  GeckoTerminal: {len(found)} winning tokens")

    if len(found) < 5:                    # fallback source
        for q in ("pumpswap", "pump SOL"):
            data = await get_json(s, f"https://api.dexscreener.com/latest/dex/search?q={q}")
            for p in (data or {}).get("pairs", []):
                try:
                    mint = p["baseToken"]["address"]
                    gain = float((p.get("priceChange") or {}).get("h24") or 0)
                    liq = float((p.get("liquidity") or {}).get("usd") or 0)
                    created = (p.get("pairCreatedAt") or 0) / 1000
                except Exception:
                    continue
                if p.get("chainId") == "solana" and mint.endswith("pump") \
                        and gain >= min_gain and liq >= 5000 and _age_ok(created, max_age):
                    found[mint] = max(gain, found.get(mint, 0))
        print(f"  after DexScreener fallback: {len(found)} winning tokens")

    ranked = sorted(found, key=lambda m: -found[m])[: CFG["discover_top_coins"]]
    return list(dict.fromkeys(list(CFG.get("seed_tokens", [])) + ranked))


async def discover(s):
    """Find wallets that actually took PROFIT on recent winning pump.fun tokens."""
    mints = await winning_tokens(s)
    print(f"analysing {len(mints)} winning tokens…")
    cnt, profit = Counter(), defaultdict(float)
    for mint in mints:
        txs = await fetch_txs(s, mint, CFG["discover_pages"])
        agg = defaultdict(lambda: [0.0, 0.0])      # wallet -> [sol_spent, sol_received]
        order = []
        for tx in sorted(txs, key=lambda t: t["timestamp"]):
            w = tx.get("feePayer")
            r = parse_swap(tx, w) if w else None
            if not r or r[0] != mint:
                continue
            if w not in order:
                order.append(w)
            agg[w][0 if r[1] == "buy" else 1] += r[3]
        skip = set(order[:3])                       # dev / bundlers / first snipers
        winners = [w for w, (sp, rc) in agg.items()
                   if w not in skip and sp >= CFG["discover_min_buy_sol"]
                   and rc >= sp * CFG["discover_min_profit_x"]]
        for w in winners:
            cnt[w] += 1
            profit[w] += agg[w][1] - agg[w][0]
        print(f"  {mint[:6]}…{mint[-4:]}  txs {len(txs)}  profitable wallets {len(winners)}")
    ranked = sorted(cnt, key=lambda w: (-cnt[w], -profit[w]))
    picks = [w for w in ranked if cnt[w] >= CFG["min_coin_appearances"]] or ranked
    return set(picks[: CFG["max_candidates"]])


async def score_wallet(s, w):
    txs = await fetch_txs(s, w, CFG["history_pages"])
    pos = defaultdict(lambda: dict(spent=0.0, recv=0.0, first_buy=None, first_sell=None))
    for tx in txs:
        r = parse_swap(tx, w)
        if not r:
            continue
        mint, side, _, sol = r
        p, ts = pos[mint], tx["timestamp"]
        if side == "buy":
            p["spent"] += sol
            p["first_buy"] = min(ts, p["first_buy"] or ts)
        else:
            p["recv"] += sol
            p["first_sell"] = min(ts, p["first_sell"] or ts)
    pnls, holds, now = [], [], time.time()
    for p in pos.values():
        if not p["spent"]:
            continue
        if p["recv"]:
            pnls.append(p["recv"] - p["spent"])
            if p["first_buy"] and p["first_sell"] and p["first_sell"] >= p["first_buy"]:
                holds.append(p["first_sell"] - p["first_buy"])
        elif p["first_buy"] and now - p["first_buy"] > 6 * 3600:
            pnls.append(-p["spent"])     # never sold + old = treat as rugged / lost
    if not pnls:
        return None
    n, wins = len(pnls), sum(1 for x in pnls if x > 0)
    m = dict(wallet=w, trades=n, win_rate=wins / n, pnl_sol=sum(pnls),
             median_hold=statistics.median(holds) if holds else 0)
    m["score"] = m["pnl_sol"] * m["win_rate"] * min(1, n / 30)
    return m


def passes(m):
    return (m["trades"] >= CFG["min_closed_trades"]
            and CFG["min_win_rate"] <= m["win_rate"] <= CFG["max_win_rate"]
            and m["median_hold"] >= CFG["min_median_hold_sec"]
            and m["pnl_sol"] >= CFG["min_realized_pnl_sol"])


async def cmd_score():
    async with aiohttp.ClientSession() as s:
        cands = set(CFG["seed_wallets"]) | await discover(s)
        print(f"scoring {len(cands)} candidate wallets…")
        res = await asyncio.gather(*(score_wallet(s, w) for w in cands))
    good = sorted((m for m in res if m and passes(m)), key=lambda m: -m["score"])
    good = good[: CFG["top_wallets"]]
    json.dump(good, open(WALLETS, "w"), indent=2)
    for m in good:
        print(f"{m['wallet'][:8]}…  pnl {m['pnl_sol']:.1f} SOL  win {m['win_rate']:.0%}  "
              f"trades {m['trades']}  hold {m['median_hold']:.0f}s")
    print(f"saved {len(good)} wallets -> wallets.json")


# ───────────────────────── Paper trading engine ─────────────────────────
class Paper:
    def __init__(self):
        self.pos = json.load(open(STATE)) if os.path.exists(STATE) else {}
        self.seen = set()
        new = not os.path.exists(TRADES)
        self.f = open(TRADES, "a", newline="")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(["time", "event", "mint", "wallet", "price_sol",
                             "x", "sol_pnl", "note"])

    def log(self, ev, mint, wallet="", price=0, x=0, pnl=0, note=""):
        self.w.writerow([time.strftime("%F %T"), ev, mint, wallet, price,
                         round(x, 2), round(pnl, 4), note])
        self.f.flush()
        print(f"[{ev}] {mint[:6]}… x{x:.2f} pnl {pnl:+.3f} SOL {note}")

    def save(self):
        json.dump(self.pos, open(STATE, "w"))

    def open(self, mint, wallet, price, symbol=""):
        fill = price * (1 + CFG["sim_slippage"])
        self.pos[mint] = dict(entry=fill, left=1.0, tier=0, wallet=wallet,
                              t0=time.time(), pnl=-CFG["fee_sol"], symbol=symbol)
        label = f"{symbol} " if symbol else ""
        self.log("BUY", mint, wallet, fill, note=f"{label}size {CFG['size_sol']} SOL")
        self.save()

    def sell(self, mint, price, frac, why):
        p = self.pos[mint]
        frac = min(frac, p["left"])
        x = price / p["entry"]
        proceeds = CFG["size_sol"] * frac * x * (1 - CFG["sim_slippage"])
        pnl = proceeds - CFG["size_sol"] * frac - CFG["fee_sol"]
        p["left"] -= frac
        p["pnl"] += pnl
        self.log("SELL", mint, p["wallet"], price, x, pnl, why)
        if p["left"] <= 1e-9:
            self.log("CLOSED", mint, p["wallet"], price, x, p["pnl"], "position total")
            del self.pos[mint]
        self.save()

    async def manage(self, s):
        """Check open positions against the exit ladder / stops."""
        while True:
            for mint in list(self.pos):
                p = self.pos[mint]
                price = await price_sol(s, mint)
                if not price:
                    continue
                x = price / p["entry"]
                p["last_x"] = x
                if x <= 1 - CFG["stop_loss_pct"]:
                    # One bad price print must not close the position. Confirm on the next poll.
                    if p.get("stop_seen"):
                        self.sell(mint, price, 1.0, "stop-loss")
                    else:
                        p["stop_seen"] = True
                    continue
                p["stop_seen"] = False
                if time.time() - p["t0"] > CFG["time_stop_min"] * 60 and x < CFG["ladder"][0]["x"]:
                    self.sell(mint, price, 1.0, "time-stop"); continue
                while p["tier"] < len(CFG["ladder"]) and x >= CFG["ladder"][p["tier"]]["x"]:
                    tier = CFG["ladder"][p["tier"]]
                    p["tier"] += 1
                    # frac of ORIGINAL size; last tier sells everything left
                    frac = p["left"] if tier["sell_frac"] >= 1 else tier["sell_frac"]
                    self.sell(mint, price, frac, f"ladder {tier['x']}X")
                    if mint not in self.pos:
                        break
            await asyncio.sleep(CFG["price_poll_sec"])

    async def on_wallet_tx(self, s, wallet, sig):
        if sig in self.seen:
            return
        self.seen.add(sig)
        r = parse_swap(await parse_sig(s, sig), wallet)
        if not r:
            return
        mint, side, tokens, sol = r
        if side == "sell":
            if CFG["follow_wallet_sells"] and mint in self.pos \
                    and self.pos[mint]["wallet"] == wallet:
                price = await price_sol(s, mint)
                if price:
                    self.sell(mint, price, self.pos[mint]["left"], "wallet sold")
            return
        if mint in self.pos or len(self.pos) >= CFG["max_open_positions"]:
            return
        price = await price_sol(s, mint)
        if not price:
            self.log("SKIP", mint, wallet, note="no price"); return
        their = sol / tokens
        if price > their * (1 + CFG["max_chase_pct"]):
            self.log("SKIP", mint, wallet, price, price / their,
                     note="price already ran vs wallet entry")
            return
        self.open(mint, wallet, price)


async def watch(eng, s, wallets):
    """Subscribe to every wallet and paper-copy its trades. Runs forever."""
    while True:                           # reconnect loop
        try:
            async with s.ws_connect(WS_URL, heartbeat=30) as ws:
                req_wallet, sub_wallet = {}, {}
                for i, w in enumerate(wallets, 1):
                    req_wallet[i] = w
                    await ws.send_json({"jsonrpc": "2.0", "id": i,
                                        "method": "logsSubscribe",
                                        "params": [{"mentions": [w]},
                                                   {"commitment": "confirmed"}]})
                async for msg in ws:
                    d = json.loads(msg.data)
                    if "id" in d and "result" in d:
                        sub_wallet[d["result"]] = req_wallet[d["id"]]
                    elif d.get("method") == "logsNotification":
                        p = d["params"]
                        v = p["result"]["value"]
                        w = sub_wallet.get(p["subscription"])
                        if w and not v.get("err"):
                            asyncio.create_task(eng.on_wallet_tx(s, w, v["signature"]))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("ws error, reconnecting:", e)
            await asyncio.sleep(3)


async def cmd_run():
    wallets = [m["wallet"] for m in json.load(open(WALLETS))]
    if not wallets:
        sys.exit("wallets.json is empty - run `score` first")
    eng = Paper()
    print(f"watching {len(wallets)} wallets (paper mode)…")
    async with aiohttp.ClientSession() as s:
        asyncio.create_task(eng.manage(s))
        await watch(eng, s, wallets)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    src = "environment variable HELIUS_API_KEY" if os.getenv("HELIUS_API_KEY") else "config.json"
    print(f"Using Helius key from {src}: {KEY[:4]}…{KEY[-3:]} (len {len(KEY)})")
    if "PASTE_YOUR" in KEY:
        sys.exit("Set your Helius key in config.json or HELIUS_API_KEY")
    if cmd == "score":
        asyncio.run(cmd_score())
    elif cmd == "run":
        asyncio.run(cmd_run())
    elif cmd == "discover":
        async def _d():
            async with aiohttp.ClientSession() as sess:
                w = await discover(sess)
                print(f"{len(w)} candidate wallets"); print("\n".join(sorted(w)))
        asyncio.run(_d())
    else:
        print(__doc__)
