"""
Jupiter quotes beside paper fills. Read-only: a quote is never a swap, and nothing is signed.

Each paper buy and sell schedules one quote for the same size. The gap says how much worse the
real route would have been than the paper fill. A missing route is logged as no_route.
"""
import asyncio
import csv
import os
import statistics

import aiohttp

import copytrader as ct
import deskio

QUOTES = os.path.join(ct.DATA, "quotes.csv")
FIELDS = ["time", "side", "mint", "usd", "paper_px", "quote_px", "gap", "impact", "route", "status", "error"]
QUOTE_URLS = ("https://lite-api.jup.ag/swap/v1/quote", "https://api.jup.ag/swap/v1/quote")
TOKEN_URL = "https://lite-api.jup.ag/tokens/v2/search?query={mint}"
SOL_MINT = ct.WSOL
_DECIMALS = {}
_SESSION = {"s": None}
_TASKS = set()


def _session():
    s = _SESSION["s"]
    if s is None or s.closed:
        s = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        _SESSION["s"] = s
    return s


async def _decimals(mint):
    if mint in _DECIMALS:
        return _DECIMALS[mint]
    dec = None
    try:
        async with _session().get(TOKEN_URL.format(mint=mint)) as resp:
            if resp.status == 200:
                for row in await resp.json(content_type=None) or []:
                    if isinstance(row, dict) and (row.get("id") == mint or row.get("address") == mint):
                        dec = int(row.get("decimals"))
                        break
    except Exception:
        dec = None
    if dec is None and mint.endswith("pump"):
        dec = 6
    if dec is not None:
        _DECIMALS[mint] = dec
    return dec


async def _quote(input_mint, output_mint, amount):
    """(quote JSON or None, error text). A 4xx with no route is a no_route, not an error."""
    last = ""
    for url in QUOTE_URLS:
        try:
            async with _session().get(
                url, params={"inputMint": input_mint, "outputMint": output_mint,
                             "amount": str(int(amount)), "slippageBps": "300"},
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and isinstance(data, dict) and data.get("outAmount"):
                    return data, ""
                text = str((data or {}).get("error") or (data or {}).get("errorCode") or resp.status)
                if "route" in text.lower() or "not tradable" in text.lower() or resp.status in (400, 404):
                    return None, "no_route"
                last = text[:80]
        except Exception as e:
            last = type(e).__name__
    return None, last or "error"


def _route(quote):
    labels = []
    for step in quote.get("routePlan") or []:
        label = (step.get("swapInfo") or {}).get("label")
        if label and label not in labels:
            labels.append(label)
    return "+".join(labels)[:80]


def _write(row):
    new = not os.path.exists(QUOTES)
    with open(QUOTES, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


async def _log(side, mint, usd, paper_px, size_sol=None, tokens=None):
    row = {"time": deskio.stamp(), "side": side, "mint": mint, "usd": round(float(usd or 0), 2),
           "paper_px": paper_px, "status": "error"}
    try:
        dec = await _decimals(mint)
        if dec is None:
            row["error"] = "unknown decimals"
            return
        if side == "buy":
            quote, err = await _quote(SOL_MINT, mint, float(size_sol) * 1e9)
            if quote:
                got = int(quote["outAmount"]) / 10 ** dec
                row["quote_px"] = float(size_sol) / got if got else ""
        else:
            quote, err = await _quote(mint, SOL_MINT, float(tokens) * 10 ** dec)
            if quote:
                row["quote_px"] = (int(quote["outAmount"]) / 1e9) / float(tokens) if tokens else ""
        if not quote:
            row["status"] = "no_route" if err == "no_route" else "error"
            row["error"] = "" if err == "no_route" else err
            return
        qp = row.get("quote_px")
        if qp and paper_px:
            row["gap"] = round(qp / paper_px - 1, 6) if side == "buy" else round(1 - qp / paper_px, 6)
        row["impact"] = quote.get("priceImpactPct", "")
        row["route"] = _route(quote)
        row["status"] = "ok"
    except Exception as e:
        row["error"] = type(e).__name__
    finally:
        try:
            _write(row)
        except OSError:
            pass


def _schedule(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def schedule_buy(mint, usd, size_sol, fill_px):
    """Quote the same SOL amount the paper buy spent. fill_px is SOL per token after paper slippage."""
    _schedule(_log("buy", mint, usd, fill_px, size_sol=size_sol))


def schedule_sell(mint, usd, tokens, paper_px):
    """Quote selling the same token amount. paper_px is SOL per token after paper slippage, before the 1% fee."""
    _schedule(_log("sell", mint, usd, paper_px, tokens=tokens))


def _pct(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]


def summary(trade_rows, limit=500):
    """Coverage, gaps, and the no-route share. Gap is how much worse the quote was than the paper fill."""
    if not os.path.exists(QUOTES):
        return {"rows": [], "n": 0, "coverage": None, "sides": {}}
    with open(QUOTES, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    first = deskio.parse_stamp(rows[0].get("time")) if rows else None
    fills = 0
    if first is not None:
        for r in trade_rows:
            if r.get("event") in ("BUY", "SELL"):
                ts = deskio.parse_stamp(r.get("time"))
                if ts is not None and ts >= first:
                    fills += 1
    sides = {}
    for side in ("buy", "sell"):
        mine = [r for r in rows if r.get("side") == side]
        gaps = []
        for r in mine:
            try:
                if r.get("status") == "ok" and r.get("gap") not in ("", None):
                    gaps.append(float(r["gap"]))
            except ValueError:
                continue
        sides[side] = {
            "n": len(mine),
            "ok": len(gaps),
            "no_route": sum(1 for r in mine if r.get("status") == "no_route"),
            "error": sum(1 for r in mine if r.get("status") == "error"),
            "median_gap": statistics.median(gaps) if gaps else None,
            "p90_gap": _pct(gaps, 0.9),
        }
    return {
        "rows": rows[-limit:],
        "n": len(rows),
        "fills": fills,
        "coverage": (min(1.0, len(rows) / fills) if fills else None),
        "sides": sides,
    }
