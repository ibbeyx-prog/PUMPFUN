"""
Paper-mode entry scanner.

Looks at pump.fun, DexScreener, Birdeye, and GMGN for the same Solana token.
A paper buy happens only when the merged score clears config.json. No real orders.
"""
import asyncio
import csv
import json
import os
import time
import urllib.request

import aiohttp

import checks
import copytrader as ct
import eye
import live
import skills
import tune

STATE = {"candidates": [], "sources": {}, "scanned_at": 0}

PUMP = "https://frontend-api-v3.pump.fun"
DEX = "https://api.dexscreener.com"
GMGN = "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps"
BIRD = "https://public-api.birdeye.so/defi/token_trending"
FOMO = "https://api.fomoapi.io/v2/leaderboard/tokens/most-held"
FOMO_EVERY = 3600
_FOMO_CACHE = {"at": 0, "rows": None, "error": ""}

BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def cfg(name, default):
    return ct.CFG.get(name, default)


def num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def blank(mint):
    return {
        "mint": mint,
        "symbol": "",
        "name": "",
        "sources": set(),
        "mcap": None,
        "liq": None,
        "change_5m": None,
        "change_1h": None,
        "holders": None,
        "smart": None,
        "rug": None,
        "bundler": None,
        "wash": False,
        "rugged": False,
        "rug_score": None,
        "rug_dangers": [],
        "rug_label": "",
        "holder_pct": None,
        "bubble_score": None,
        "bubble_cluster": None,
        "bubble_top10": None,
        "bubble_label": "",
        "price_sol": None,
        "age_min": None,
        "pump": False,
        "live": False,
    }


def touch(book, mint):
    if mint not in book:
        book[mint] = blank(mint)
    return book[mint]


def age_min(ts):
    if not ts:
        return None
    ts = float(ts)
    if ts > 1e12:
        ts /= 1000
    return max(0, (time.time() - ts) / 60)


def _http_get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


async def get_json_browser(url, headers):
    """Cloudflare blocks aiohttp on GMGN. urllib still gets through."""
    return await asyncio.to_thread(_http_get, url, headers)


def bird_key():
    import os
    return os.getenv("BIRDEYE_API_KEY") or ct.CFG.get("birdeye_api_key") or ""


def fomo_key():
    return os.getenv("FOMO_API_KEY") or ""


def _fomo_list(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("tokens", "data", "items", "leaderboard", "results"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
        if isinstance(rows, dict):
            for inner in ("tokens", "items", "data"):
                if isinstance(rows.get(inner), list):
                    return rows[inner]
    return []


def _sol_mint(row):
    if not isinstance(row, dict):
        return ""
    chain = str(row.get("chain") or row.get("chainId") or row.get("network") or "").lower()
    # 1399811149 is the Solana chain id FOMO uses on its token board.
    if chain and chain not in ("sol", "solana", "1399811149"):
        return ""
    for key in ("address", "mint", "contractAddress", "tokenAddress", "ca"):
        val = row.get(key)
        if isinstance(val, str) and not val.startswith("0x") and 32 <= len(val) <= 44:
            return val
    token = row.get("token") or row.get("baseToken") or {}
    if isinstance(token, dict) and token is not row:
        return _sol_mint({**token, "chain": chain or token.get("chain") or "solana"})
    return ""


async def sol_usd(session):
    price = await ct.sol_usd(session)
    if price:
        STATE["sol_usd"] = price
        STATE["sol_usd_at"] = time.time()
    return price


async def from_pump(session, book):
    headers = {**BROWSER, "Origin": "https://pump.fun", "Referer": "https://pump.fun/"}
    urls = [
        f"{PUMP}/coins?offset=0&limit=40&sort=last_trade_timestamp&order=DESC&includeNsfw=false",
        f"{PUMP}/coins/currently-live?offset=0&limit=20&includeNsfw=false",
    ]
    n = 0
    sol = await sol_usd(session)
    for i, url in enumerate(urls):
        rows = await ct.get_json(session, url, headers)
        if not isinstance(rows, list):
            continue
        for coin in rows:
            mint = coin.get("mint")
            if not mint:
                continue
            c = touch(book, mint)
            c["sources"].add("pump.fun")
            c["symbol"] = c["symbol"] or coin.get("symbol") or ""
            c["name"] = c["name"] or coin.get("name") or ""
            c["pump"] = True
            c["live"] = c["live"] or i == 1 or bool(coin.get("is_currently_live"))
            mcap = num(coin.get("usd_market_cap"))
            if mcap:
                c["mcap"] = mcap
            created = coin.get("created_timestamp")
            if c["age_min"] is None:
                c["age_min"] = age_min(created)
            v_sol = num(coin.get("virtual_sol_reserves"), 0)
            v_tok = num(coin.get("virtual_token_reserves"), 0)
            if v_sol and v_tok and not c["price_sol"]:
                c["price_sol"] = (v_sol / 1e9) / (v_tok / 1e6)
            real_sol = num(coin.get("real_sol_reserves"), 0) / 1e9
            if sol and real_sol and not c["liq"]:
                c["liq"] = real_sol * sol
            n += 1
    return n


async def from_dex(session, book):
    headers = {**BROWSER, "Origin": "https://dexscreener.com", "Referer": "https://dexscreener.com/"}
    mints = []
    for path in ("/token-boosts/latest/v1", "/token-boosts/top/v1", "/token-profiles/latest/v1"):
        rows = await ct.get_json(session, DEX + path, headers)
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("pairs") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if row.get("chainId") not in (None, "solana"):
                continue
            mint = row.get("tokenAddress") or row.get("address")
            if not mint:
                continue
            c = touch(book, mint)
            c["sources"].add("dexscreener")
            mints.append(mint)
    uniq = list(dict.fromkeys(mints))[:30]
    if not uniq:
        return 0
    data = await ct.get_json(session, f"{DEX}/latest/dex/tokens/{','.join(uniq)}")
    best = {}
    for pair in (data or {}).get("pairs") or []:
        if pair.get("chainId") != "solana":
            continue
        base = (pair.get("baseToken") or {}).get("address")
        if not base:
            continue
        liq = (pair.get("liquidity") or {}).get("usd") or 0
        if base not in best or liq > best[base][0]:
            best[base] = (liq, pair)
    for mint, (_, pair) in best.items():
        c = touch(book, mint)
        c["sources"].add("dexscreener")
        base = pair.get("baseToken") or {}
        c["symbol"] = c["symbol"] or base.get("symbol") or ""
        c["name"] = c["name"] or base.get("name") or ""
        ch = pair.get("priceChange") or {}
        c["change_5m"] = c["change_5m"] if c["change_5m"] is not None else num(ch.get("m5"))
        c["change_1h"] = c["change_1h"] if c["change_1h"] is not None else num(ch.get("h1"))
        liq = num((pair.get("liquidity") or {}).get("usd"))
        if liq:
            c["liq"] = liq
        mcap = num(pair.get("marketCap")) or num(pair.get("fdv"))
        if mcap:
            c["mcap"] = mcap
        if (pair.get("quoteToken") or {}).get("address") == ct.WSOL:
            c["price_sol"] = c["price_sol"] or num(pair.get("priceNative"))
        created = num(pair.get("pairCreatedAt"))
        if c["age_min"] is None and created:
            c["age_min"] = age_min(created)
        if (mint or "").endswith("pump"):
            c["pump"] = True
    return len(uniq)


async def from_gmgn(session, book):
    headers = {**BROWSER, "Origin": "https://gmgn.ai", "Referer": "https://gmgn.ai/"}
    n = 0
    for window in ("5m", "1h"):
        data = await get_json_browser(
            f"{GMGN}/{window}?orderby=volume&direction=desc",
            headers,
        )
        rows = ((data or {}).get("data") or {}).get("rank") or []
        if not isinstance(rows, list):
            continue
        for row in rows[:40]:
            mint = row.get("address")
            if not mint:
                continue
            c = touch(book, mint)
            c["sources"].add("gmgn")
            c["symbol"] = c["symbol"] or row.get("symbol") or ""
            c["name"] = c["name"] or row.get("name") or ""
            if window == "5m" or c["change_5m"] is None:
                c["change_5m"] = num(row.get("price_change_percent5m"))
                if c["change_5m"] is None and window == "5m":
                    c["change_5m"] = num(row.get("price_change_percent"))
            c["change_1h"] = c["change_1h"] if c["change_1h"] is not None else num(row.get("price_change_percent1h"))
            liq = num(row.get("liquidity"))
            if liq:
                c["liq"] = liq
            mcap = num(row.get("market_cap"))
            if mcap:
                c["mcap"] = mcap
            c["holders"] = c["holders"] or num(row.get("holder_count"))
            c["smart"] = c["smart"] or num(row.get("smart_degen_count"))
            c["rug"] = c["rug"] if c["rug"] is not None else num(row.get("rug_ratio"))
            c["bundler"] = c["bundler"] if c["bundler"] is not None else num(row.get("bundler_rate"))
            c["wash"] = c["wash"] or bool(row.get("is_wash_trading"))
            c["price_sol"] = c["price_sol"] or None
            if c["age_min"] is None:
                c["age_min"] = age_min(row.get("creation_timestamp"))
            platform = (row.get("launchpad_platform") or row.get("launchpad") or "").lower()
            if "pump" in platform or mint.endswith("pump"):
                c["pump"] = True
            n += 1
    return n


async def from_birdeye(session, book):
    key = bird_key()
    if not key:
        return 0, "set BIRDEYE_API_KEY to include Birdeye"
    headers = {
        **BROWSER,
        "X-API-KEY": key,
        "x-chain": "solana",
        "Origin": "https://birdeye.so",
        "Referer": "https://birdeye.so/",
    }
    url = f"{BIRD}?sort_by=rank&sort_type=asc&interval=1h&offset=0&limit=20"
    data = await ct.get_json(session, url, headers)
    rows = data
    if isinstance(data, dict):
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        rows = (inner or {}).get("tokens") or (inner or {}).get("items") or data.get("tokens") or []
    if not isinstance(rows, list):
        return 0, "unexpected response"
    for row in rows:
        mint = row.get("address") or row.get("tokenAddress")
        if not mint:
            continue
        c = touch(book, mint)
        c["sources"].add("birdeye")
        c["symbol"] = c["symbol"] or row.get("symbol") or ""
        c["name"] = c["name"] or row.get("name") or ""
        liq = num(row.get("liquidity"))
        if liq:
            c["liq"] = liq
        mcap = num(row.get("marketcap") or row.get("mc") or row.get("marketCap"))
        if mcap:
            c["mcap"] = mcap
        if mint.endswith("pump"):
            c["pump"] = True
    return len(rows), ""


async def from_fomo(session, book):
    """Most-held Solana names from FOMO. Cached for an hour so a free key survives."""
    key = fomo_key()
    if not key:
        return 0, "set FOMO_API_KEY to include FOMO"
    now = time.time()
    wait = 600 if _FOMO_CACHE["error"] else FOMO_EVERY
    fresh = _FOMO_CACHE["rows"] is not None and now - _FOMO_CACHE["at"] < wait
    if not fresh:
        headers = {**BROWSER, "Authorization": f"Bearer {key}"}
        try:
            async with session.get(FOMO, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 401:
                    _FOMO_CACHE.update(at=now, rows=[], error="FOMO key was rejected")
                elif resp.status == 402:
                    _FOMO_CACHE.update(at=now, rows=[], error="FOMO credits used up")
                elif resp.status != 200:
                    _FOMO_CACHE.update(at=now, rows=[], error=f"FOMO HTTP {resp.status}")
                else:
                    data = await resp.json(content_type=None)
                    _FOMO_CACHE.update(at=now, rows=_fomo_list(data), error="")
        except Exception as exc:
            _FOMO_CACHE.update(at=now, rows=[], error=str(exc)[:120])
    if _FOMO_CACHE["error"]:
        return 0, _FOMO_CACHE["error"]
    n = 0
    for row in _FOMO_CACHE["rows"] or []:
        mint = _sol_mint(row)
        if not mint:
            continue
        c = touch(book, mint)
        c["sources"].add("fomo")
        token = row.get("token") if isinstance(row.get("token"), dict) else {}
        c["symbol"] = c["symbol"] or row.get("symbol") or token.get("symbol") or ""
        c["name"] = c["name"] or row.get("name") or token.get("name") or ""
        if c["mcap"] is None:
            c["mcap"] = num(row.get("marketCapUsd") or row.get("marketCap"))
        if mint.endswith("pump"):
            c["pump"] = True
        n += 1
    if n == 0:
        return 0, "FOMO returned no Solana names"
    return n, ""


def decide(c):
    score = 0
    notes = []
    src = c["sources"]
    min_sources = int(tune.value("min_sources", 1))
    entry_score = float(tune.value("entry_score", cfg("entry_score", 60)))
    max_change = float(tune.value("max_change_5m", cfg("max_change_5m", 90)))
    if "pump.fun" in src:
        score += 12
    if "dexscreener" in src:
        score += 12
    if "gmgn" in src:
        score += 18
    if "birdeye" in src:
        score += 12
    if "fomo" in src:
        score += 12
    if len(src) >= 2:
        score += 15
        notes.append(f"{len(src)} sources")
    if c["pump"]:
        score += 8
    ch = c["change_5m"]
    if ch is not None:
        lo, hi = cfg("min_change_5m", 5), max_change
        if lo <= ch <= hi:
            score += 20
            notes.append(f"5m {ch:.0f}%")
        elif ch > hi:
            score -= 25
            notes.append(f"already ran {ch:.0f}%")
        else:
            notes.append(f"5m {ch:.0f}% flat")
    rules = eye.tool_rules()
    if (c["smart"] or 0) >= 3 and rules["late_copy"]:
        notes.append("eye: copy arrives late")
    elif (c["smart"] or 0) >= 3:
        score += 12
        notes.append(f"{int(c['smart'])} smart wallets")
    if (c["holders"] or 0) >= 80:
        score += 6
    if c["live"]:
        score += 4
        notes.append("live")
    if (c["liq"] or 0) >= cfg("min_liquidity_usd", 8000) * 2:
        score += 6

    hard = []
    mcap, liq = c["mcap"], c["liq"]
    if mcap is not None and not (cfg("min_mcap_usd", 6000) <= mcap <= cfg("max_mcap_usd", 800000)):
        hard.append("mcap outside range")
    if liq is not None and liq < cfg("min_liquidity_usd", 8000):
        hard.append("thin liquidity")
    if liq is None and "gmgn" not in src and "dexscreener" not in src:
        hard.append("no liquidity yet")
    if c["rug"] is not None and c["rug"] > cfg("max_rug_ratio", 0.4):
        hard.append("rug risk")
    if c["bundler"] is not None and c["bundler"] > cfg("max_bundler_rate", 0.35):
        hard.append("bundled")
    if c["wash"]:
        hard.append("wash trading")
    age = c["age_min"]
    if age is not None and age < cfg("min_age_min", 2):
        hard.append("too new")
    if age is not None and age > cfg("max_age_hours", 36) * 60:
        hard.append("too old")
    if ch is not None and ch > max_change:
        hard.append("chasing")
    if len(src) < min_sources:
        hard.append(f"agent wants {min_sources} sources")
    hard.extend(skills.blocks(c))
    hard.extend(checks.blocks(c))
    if not hard and c.get("rug_score") is not None and float(c["rug_score"]) < 15 and not c.get("rug_dangers"):
        score += 8
        notes.append(f"rugcheck {float(c['rug_score']):.0f}")
    if not hard and c.get("bubble_score") is not None and float(c["bubble_score"]) >= 60:
        score += 8
        notes.append(f"bubblemap {float(c['bubble_score']):.0f}")

    confirmed = "gmgn" in src or "dexscreener" in src or "birdeye" in src
    if hard:
        decision = "skip"
        notes.extend(hard)
    elif score >= entry_score and confirmed and ch is not None and cfg("min_change_5m", 5) <= ch <= max_change:
        decision = "enter"
    else:
        decision = "watch"
        if not confirmed:
            notes.append("needs dex, birdeye, or gmgn")
        elif ch is None:
            notes.append("no 5m move yet")
    return score, decision, ", ".join(notes) or "watching"


def public(c, score, decision, note):
    return {
        "mint": c["mint"],
        "symbol": c["symbol"] or c["mint"][:4],
        "name": c["name"],
        "sources": sorted(c["sources"]),
        "score": score,
        "decision": decision,
        "note": note,
        "mcap": None if c["mcap"] is None else round(c["mcap"]),
        "liq": None if c["liq"] is None else round(c["liq"]),
        "change_5m": None if c["change_5m"] is None else round(c["change_5m"], 1),
        "holders": None if c["holders"] is None else int(c["holders"]),
        "price_sol": c["price_sol"],
        "age_min": None if c["age_min"] is None else round(c["age_min"]),
        "rug_score": None if c.get("rug_score") is None else round(float(c["rug_score"])),
        "rug_label": c.get("rug_label") or "",
        "holder_pct": None if c.get("holder_pct") is None else round(float(c["holder_pct"]), 1),
        "bubble_score": None if c.get("bubble_score") is None else round(float(c["bubble_score"])),
        "bubble_cluster": None if c.get("bubble_cluster") is None else round(float(c["bubble_cluster"]), 3),
        "bubble_label": c.get("bubble_label") or "",
        "bubble_url": checks.map_url(c["mint"]),
    }


def bought_recently(mint):
    cool = float(cfg("entry_cooldown_min", 180)) * 60
    if not os.path.exists(ct.TRADES):
        return False
    now = time.time()
    with open(ct.TRADES, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("mint") != mint or row.get("event") != "BUY":
                continue
            try:
                ts = time.mktime(time.strptime(row["time"], "%Y-%m-%d %H:%M:%S"))
            except (KeyError, ValueError):
                continue
            if now - ts < cool:
                return True
    return False


async def scan_once(session):
    book = {}
    sources = {}

    async def run(name, fn):
        try:
            result = await fn()
            if isinstance(result, tuple):
                n, err = result
                sources[name] = {"ok": not err, "n": n, "error": err}
            else:
                sources[name] = {"ok": True, "n": result, "error": ""}
        except Exception as e:
            sources[name] = {"ok": False, "n": 0, "error": str(e)[:120]}
            print(f"scan {name} failed: {e!r}")

    await run("pump.fun", lambda: from_pump(session, book))
    await run("dexscreener", lambda: from_dex(session, book))
    await run("gmgn", lambda: from_gmgn(session, book))
    await run("birdeye", lambda: from_birdeye(session, book))
    await run("fomo", lambda: from_fomo(session, book))

    ranked = []
    for c in book.values():
        if len(c["sources"]) == 1 and "pump.fun" in c["sources"] and not c["live"] and (c["mcap"] or 0) < cfg("min_mcap_usd", 6000):
            continue
        score, decision, note = decide(c)
        row = public(c, score, decision, note)
        row["_price"] = c["price_sol"]
        row["_c"] = c
        ranked.append(row)

    review = [r for r in ranked if r["decision"] != "skip"][:8]
    rug_ok = bubble_ok = 0
    if review:
        sem = asyncio.Semaphore(4)

        async def review_one(row):
            async with sem:
                rug, bubble = await asyncio.gather(
                    checks.rugcheck(session, row["mint"]),
                    checks.bubblemap(session, row["mint"]),
                )
            return row, rug, bubble

        for row, rug, bubble in await asyncio.gather(*(review_one(r) for r in review)):
            checks.apply(row["_c"], rug, bubble)
            if rug and rug.get("ok"):
                rug_ok += 1
            if bubble and bubble.get("ok"):
                bubble_ok += 1
            score, decision, note = decide(row["_c"])
            fresh = public(row["_c"], score, decision, note)
            fresh["_price"] = row.get("_price")
            fresh["_c"] = row["_c"]
            row.clear()
            row.update(fresh)
    sources["rugcheck"] = {"ok": True, "n": rug_ok, "error": ""}
    if checks.bubble_key():
        sources["bubblemap"] = {"ok": bubble_ok > 0 or not review, "n": bubble_ok, "error": ""}
    else:
        sources["bubblemap"] = {"ok": False, "n": 0, "error": "set BUBBLEMAPS_API_KEY"}

    for row in ranked:
        row.pop("_c", None)
    ranked.sort(key=lambda r: ({"enter": 0, "watch": 1, "skip": 2}[r["decision"]], -r["score"]))
    return ranked, sources


async def scan_loop(eng, session, status):
    while True:
        tune.review()
        eye.tend_wallet(eng)
        eye.choose_trade_usd()
        ranked, sources = await scan_once(session)
        skills.observe(ranked)
        shown = []
        for row in ranked[:25]:
            item = dict(row)
            item.pop("_price", None)
            shown.append(item)
        STATE["candidates"] = shown
        STATE["sources"] = sources
        STATE["scanned_at"] = time.time()
        ok = [name for name, s in sources.items() if s.get("ok")]
        status["phase"] = "scanning " + ", ".join(ok or ["no sources"])
        status["sources"] = {k: v.get("error") or f"{v.get('n', 0)} tokens" for k, v in sources.items()}

        entered = 0
        limit = min(
            int(tune.value("max_new_entries_per_scan", cfg("max_new_entries_per_scan", 1))),
            skills.MAX_NEW,
        )
        for row in ranked:
            if row["decision"] != "enter":
                continue
            if len(eng.pos) >= ct.CFG["max_open_positions"]:
                break
            if entered >= limit:
                break
            mint = row["mint"]
            if mint in eng.pos or bought_recently(mint):
                continue
            # Fill at the DexScreener price. The exit loop uses that same price,
            # so a pump.fun curve quote cannot open a position that instantly stops out.
            price = await ct.price_sol(session, mint)
            if not price:
                eng.log("SKIP", mint, "+".join(row["sources"]), note="no DexScreener SOL price")
                continue
            usd = eye.choose_trade_usd()
            if usd < 4:
                eng.log("SKIP", mint, "+".join(row["sources"]), note="fee reserve leaves less than $4")
                continue
            opened = await eng.buy(session, mint, "+".join(row["sources"]), price, symbol=row.get("symbol") or "")
            if not opened:
                continue
            live.queue_phantom(mint, row.get("symbol") or "", usd)
            entered += 1
        if entered:
            status["phase"] = f"paper entry · {status['phase']}"
        await asyncio.sleep(float(cfg("scan_sec", 45)))
