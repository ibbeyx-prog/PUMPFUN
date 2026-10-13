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
CFG.setdefault("budget_usd", 50)
CFG.setdefault("trade_usd", 5)
CFG.setdefault("reserve_usd", 5)
CFG.setdefault("one_trade_per_coin", True)
KEY = os.getenv("HELIUS_API_KEY") or CFG["helius_api_key"]
DATA = os.getenv("DATA_DIR", ".")            # on Railway: mount a volume here
os.makedirs(DATA, exist_ok=True)
WALLETS = os.path.join(DATA, "wallets.json")
TRADES = os.path.join(DATA, "trades.csv")
STATE = os.path.join(DATA, "state.json")
BANK = os.path.join(DATA, "bank.json")
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


ENTRY_DELAY_S = 45
POSITION_POLL_S = 12
FEE_PCT = 0.01
FLAT_USD = 0.20


def slip_pct(trade_usd, liq_usd):
    """3% plus constant-product impact. Unknown liquidity stays at 3%. A thin pool is capped at 80%."""
    liq = float(liq_usd or 0)
    if liq <= 0:
        return 0.03
    return min(0.80, 0.03 + 2.0 * float(trade_usd or 0) / liq)


def flat_sol(px):
    if not px:
        return 0.0
    return FLAT_USD / float(px)


async def price_quote(s, mint):
    """Return (price SOL, liquidity USD, confirmed missing).

    The third value is true only when DexScreener answered and had no sane WSOL pair.
    A timeout or a rate limit is not a missing token, so it cannot trigger a vanish exit.
    Dust pools that imply an impossible SOL price are ignored.
    """
    try:
        async with s.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}") as r:
            if r.status != 200:
                return None, None, False
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
            return None, None, True
        liquid = [g for g in good if g[0] >= 500]
        liq, native = max(liquid or good)
        return native, liq, False
    except Exception:
        return None, None, False


async def price_sol(s, mint):
    price, _liq, _missing = await price_quote(s, mint)
    return price


# ───────────────────────── Discovery + scoring ─────────────────────────
_SOL = {"price": None, "at": 0}


async def sol_usd(session):
    """SOL price in USD. DexScreener first, CoinGecko if that fails. Cached 60s."""
    now = time.time()
    if _SOL["price"] and now - _SOL["at"] < 60:
        return _SOL["price"]
    price = None
    data = await get_json(session, f"https://api.dexscreener.com/latest/dex/tokens/{WSOL}")
    pairs = [
        p for p in (data or {}).get("pairs") or []
        if p.get("chainId") == "solana" and (p.get("baseToken") or {}).get("address") == WSOL
    ]
    if pairs:
        best = max(pairs, key=_pair_liq)
        try:
            price = float(best.get("priceUsd") or 0) or None
        except (TypeError, ValueError):
            price = None
    if not price:
        data = await get_json(session, "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
        try:
            price = float(((data or {}).get("solana") or {}).get("usd") or 0) or None
        except (TypeError, ValueError):
            price = None
    if price and 20 <= price <= 1000:
        _SOL["price"] = price
        _SOL["at"] = now
        return price
    return _SOL["price"]


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
        for p in self.pos.values():
            if not p.get("size_sol"):
                p["size_sol"] = 0.1
        self.pending = {}
        self.bought = set()
        if os.path.exists(TRADES):
            with open(TRADES, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if row.get("event") == "BUY" and row.get("mint"):
                        self.bought.add(row["mint"])
        self.bank = json.load(open(BANK)) if os.path.exists(BANK) else None
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

    def _save_bank(self):
        json.dump(self.bank, open(BANK, "w"), indent=2)

    def equity_usd(self, px):
        if not self.bank or not px:
            return None
        sol = float(self.bank.get("start_sol") or 0) + float(self.bank.get("realized_sol") or 0)
        for p in self.pos.values():
            held = self._pos_size(p) * float(p.get("left") or 0)
            sol += held * ((p.get("last_x") or 1) - 1)
        return sol * float(px)

    def refill(self, px):
        """Start the paper wallet over at the budget. Does not touch a real Phantom account."""
        if not px:
            return False
        self.pos.clear()
        self.save()
        self.bank = {
            "start_usd": float(CFG["budget_usd"]),
            "start_sol": float(CFG["budget_usd"]) / float(px),
            "realized_sol": 0.0,
        }
        self._save_bank()
        self.log("RESET", "", "paper", note="refilled to $50")
        return True

    def _ensure_bank(self, px):
        if self.bank:
            return
        self.bank = {
            "start_usd": float(CFG["budget_usd"]),
            "start_sol": float(CFG["budget_usd"]) / px,
            "realized_sol": 0.0,
        }
        self._save_bank()

    def _pos_size(self, p):
        return float(p.get("size_sol") or 0)

    def fee_reserve_usd(self):
        """SOL kept in the wallet for fees, the way a Phantom balance would. Always $3 to $5."""
        raw = float(CFG.get("reserve_usd") or 5)
        return min(5.0, max(3.0, raw))

    def free_sol(self, px):
        if not self.bank or not px:
            return 0.0
        deployed = sum(self._pos_size(p) * float(p.get("left") or 0) for p in self.pos.values())
        deployed += sum(float(item.get("size_sol") or 0) for item in self.pending.values())
        reserve = self.fee_reserve_usd() / px
        return float(self.bank["start_sol"]) + float(self.bank.get("realized_sol") or 0) - deployed - reserve

    def budget_view(self):
        px = _SOL.get("price")
        bank = self.bank or {}
        start_sol = float(bank.get("start_sol") or 0)
        realized = float(bank.get("realized_sol") or 0)
        deployed = sum(self._pos_size(p) * float(p.get("left") or 0) for p in self.pos.values())
        deployed += sum(float(item.get("size_sol") or 0) for item in self.pending.values())
        unreal = 0.0
        for p in self.pos.values():
            held = self._pos_size(p) * float(p.get("left") or 0)
            unreal += held * ((p.get("last_x") or 1) - 1)
        reserve = self.fee_reserve_usd()
        free = self.free_sol(px) if px and bank else None

        def usd(sol):
            return None if not px or sol is None else round(sol * px, 2)

        start_usd = bank.get("start_usd")
        if start_usd is None:
            start_usd = float(CFG["budget_usd"])
        return {
            "sol_usd": None if not px else round(px, 2),
            "start_usd": round(float(start_usd), 2),
            "equity_usd": usd(start_sol + realized + unreal) if bank else round(float(start_usd), 2),
            "realized_usd": usd(realized) if bank else 0,
            "deployed_usd": usd(deployed) if bank else 0,
            "available_usd": usd(free) if free is not None else round(float(CFG["budget_usd"]) - reserve, 2),
            "reserve_usd": reserve,
            "trade_usd": float(CFG["trade_usd"]),
        }

    async def buy(self, session, mint, wallet, price, symbol=""):
        if CFG.get("one_trade_per_coin", True) and (mint in self.bought or mint in self.pos or mint in self.pending):
            self.log("SKIP", mint, wallet, note="already bought this coin")
            return False
        px = await sol_usd(session)
        if not px:
            self.log("SKIP", mint, wallet, note="no SOL price for budget")
            return False
        self._ensure_bank(px)
        size = float(CFG["trade_usd"]) / px
        free = self.free_sol(px)
        if size > free + 1e-9:
            self.log("SKIP", mint, wallet, note=f"budget: need {size:.4f} SOL, free {free:.4f} SOL")
            return False
        self.pending[mint] = {
            "wallet": wallet,
            "symbol": symbol,
            "size_sol": size,
            "trade_usd": float(CFG["trade_usd"]),
            "at": time.time(),
        }
        return True

    def open(self, mint, wallet, price, symbol="", size_sol=None, liq_usd=None, trade_usd=None, sol_px=None):
        if not size_sol or size_sol <= 0 or not price:
            self.log("SKIP", mint, wallet, note="budget: no trade size")
            return
        usd = float(trade_usd if trade_usd is not None else CFG.get("trade_usd") or 0)
        fill = price * (1 + slip_pct(usd, liq_usd))
        fee = float(size_sol) * FEE_PCT + flat_sol(sol_px)
        self.pos[mint] = dict(entry=fill, left=1.0, tier=0, wallet=wallet,
                              t0=time.time(), pnl=-fee, symbol=symbol,
                              size_sol=float(size_sol), liq_usd=float(liq_usd or 0),
                              last_price=float(price), last_x=(price / fill) if fill else 1,
                              misses=0, stop_armed=False)
        self.bought.add(mint)
        if self.bank is not None and fee:
            self.bank["realized_sol"] = float(self.bank.get("realized_sol") or 0) - fee
            self._save_bank()
        label = f"{symbol} " if symbol else ""
        self.log("BUY", mint, wallet, fill, note=f"{label}size {size_sol:.4f} SOL · ${usd:.2f} phantom paper")
        self.save()
        try:
            import live
            live.queue_phantom(mint, symbol, usd)
        except Exception:
            pass

    def sell(self, mint, price, frac, why, liq_usd=None, sol_px=None):
        p = self.pos[mint]
        frac = min(frac, p["left"])
        size = self._pos_size(p)
        entry = float(p["entry"] or 0)
        x = (price / entry) if entry else 0
        gross = size * frac * x
        notional = gross * float(sol_px or 0)
        pool = liq_usd if liq_usd is not None else p.get("liq_usd")
        slip = slip_pct(notional or float(CFG.get("trade_usd") or 0) * frac, pool)
        proceeds = gross * (1 - slip) * (1 - FEE_PCT) - flat_sol(sol_px)
        pnl = proceeds - size * frac
        p["left"] -= frac
        p["pnl"] += pnl
        if self.bank is not None:
            self.bank["realized_sol"] = float(self.bank.get("realized_sol") or 0) + pnl
            self._save_bank()
        self.log("SELL", mint, p["wallet"], price, x, pnl, why)
        try:
            import live
            live.queue_sell(mint, p.get("symbol") or "", frac, why)
        except Exception:
            pass
        if p["left"] <= 1e-9:
            self.log("CLOSED", mint, p["wallet"], price, x, p["pnl"], "position total")
            del self.pos[mint]
        self.save()

    async def _fill_pending(self, s, sol_px):
        now = time.time()
        for mint in list(self.pending):
            item = self.pending[mint]
            age = now - float(item.get("at") or now)
            if age < ENTRY_DELAY_S:
                continue
            if age > 70:
                self.pending.pop(mint, None)
                self.log("SKIP", mint, item.get("wallet") or "", note="missed the 45s entry price")
                continue
            price, liq, _missing = await price_quote(s, mint)
            if not price:
                continue
            self.pending.pop(mint, None)
            self.open(
                mint, item.get("wallet") or "", price, symbol=item.get("symbol") or "",
                size_sol=item.get("size_sol"), liq_usd=liq, trade_usd=item.get("trade_usd"),
                sol_px=sol_px,
            )

    async def manage(self, s):
        """Check open positions against the exit ladder / stops. Polls every 12s."""
        while True:
            sol_px = await sol_usd(s)
            await self._fill_pending(s, sol_px)
            for mint in list(self.pos):
                p = self.pos.get(mint)
                if not p:
                    continue
                price, liq, missing = await price_quote(s, mint)
                if not price:
                    if not missing:
                        continue
                    p["misses"] = int(p.get("misses") or 0) + 1
                    if p["misses"] >= 3:
                        last = float(p.get("last_price") or 0) or float(p.get("entry") or 0)
                        self.sell(mint, last * 0.10, 1.0, "vanished", liq_usd=0, sol_px=sol_px)
                    continue
                p["misses"] = 0
                p["last_price"] = price
                if p.get("stop_armed"):
                    self.sell(mint, price, 1.0, "stop-loss", liq_usd=liq, sol_px=sol_px)
                    continue
                x = price / p["entry"] if p.get("entry") else 0
                p["last_x"] = x
                entry_liq = float(p.get("liq_usd") or 0)
                if entry_liq and liq is not None and liq <= entry_liq * 0.5:
                    self.sell(mint, price, 1.0, "liquidity pulled", liq_usd=liq, sol_px=sol_px)
                    continue
                if x <= 1 - CFG["stop_loss_pct"]:
                    p["stop_armed"] = True
                    continue
                import tune
                cut_x = tune.value("early_cut_x")
                cut_min = float(tune.value("early_cut_min") or 10)
                age_min = (time.time() - p["t0"]) / 60
                if cut_x and age_min >= cut_min and x <= float(cut_x) and x < CFG["ladder"][0]["x"]:
                    if p.get("cut_seen"):
                        sym = p.get("symbol") or mint[:6]
                        self.sell(mint, price, 1.0, "agent cut", liq_usd=liq, sol_px=sol_px)
                        tune.note("exit", sym, f"{x:.2f}x",
                                  f"cut under {cut_x}x after {int(cut_min)}m")
                    else:
                        p["cut_seen"] = True
                    continue
                p["cut_seen"] = False
                if time.time() - p["t0"] > CFG["time_stop_min"] * 60 and x < CFG["ladder"][0]["x"]:
                    self.sell(mint, price, 1.0, "time-stop", liq_usd=liq, sol_px=sol_px)
                    continue
                # The 5x ladder stays. A 2x sale plus a 30% trail is not used until the
                # lab's desk-runner book beats this ladder with its interval above zero.
                while mint in self.pos and p["tier"] < len(CFG["ladder"]) and x >= CFG["ladder"][p["tier"]]["x"]:
                    tier = CFG["ladder"][p["tier"]]
                    p["tier"] += 1
                    frac = p["left"] if tier["sell_frac"] >= 1 else tier["sell_frac"]
                    self.sell(mint, price, frac, f"ladder {tier['x']}X", liq_usd=liq, sol_px=sol_px)
                    p = self.pos.get(mint)
                    if not p:
                        break
            await asyncio.sleep(POSITION_POLL_S)

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
        await self.buy(s, mint, wallet, price)


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
