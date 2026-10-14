"""
Guards for real-money execution. Eye may halt this, never resume it.

Nothing is signed or broadcast unless a wallet key is present, and even then
the order is refused when a USD limit, the reserve, or a halt says no.
Paper mode does not need this module's key.
"""
import hashlib
import json
import os
import secrets
import time
import urllib.request

import aiohttp

import copytrader as ct
import deskio

HALT_PATH = os.path.join(ct.DATA, "live_state.json")
LOCKED = ("budget_usd", "trade_usd", "reserve_usd", "one_trade_per_coin")


def _env_usd(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def max_trade_usd():
    return _env_usd("LIVE_MAX_TRADE_USD", "15")


def max_exposure_usd():
    return _env_usd("LIVE_MAX_EXPOSURE_USD", "45")


def max_daily_loss_usd():
    return _env_usd("LIVE_DAILY_LOSS_USD", "15")


def _load():
    if not os.path.exists(HALT_PATH):
        return {"halted": False, "reason": "", "failures": 0, "stuck_sell": False,
                "exposure_usd": 0.0, "daily_loss_usd": 0.0, "day": ""}
    try:
        with open(HALT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("halted", False)
    data.setdefault("reason", "")
    data.setdefault("failures", 0)
    data.setdefault("stuck_sell", False)
    data.setdefault("exposure_usd", 0.0)
    data.setdefault("daily_loss_usd", 0.0)
    data.setdefault("day", "")
    data.setdefault("phantom", "")
    data.setdefault("wallet_trade", False)
    data.setdefault("orders", [])
    data.setdefault("positions", [])
    return data


def _save(data):
    deskio.write_json(HALT_PATH, data)


def sol_price():
    return ct._SOL.get("price") or 0


def _today(data):
    day = deskio.stamp()[:10]
    if data.get("day") != day:
        data["day"] = day
        data["daily_loss_usd"] = 0.0
    return data


def paper_profit_sol():
    if not os.path.exists(ct.TRADES):
        return 0.0
    import csv
    total = 0.0
    with open(ct.TRADES, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("event") == "CLOSED":
                try:
                    total += float(row.get("sol_pnl") or 0)
                except ValueError:
                    continue
    return total


def halt(reason):
    """Stop live trading. The agent cannot turn it back on."""
    data = _load()
    data["halted"] = True
    data["reason"] = str(reason)[:160]
    if reason != "paper mode":
        data["wallet_trade"] = False
    _save(data)


def note_failure(reason="order failed"):
    data = _load()
    data["failures"] = int(data.get("failures") or 0) + 1
    _save(data)
    if data["failures"] >= 3:
        halt(reason)


def note_stuck_sell():
    data = _load()
    data["stuck_sell"] = True
    _save(data)
    halt("stuck sell")


def signature_verdict(status):
    """What getSignatureStatuses said about one signature. Empty input is rejected by the caller."""
    if not isinstance(status, dict):
        return "missing"
    if status.get("err"):
        return "failed"
    if status.get("confirmationStatus") in ("confirmed", "finalized"):
        return "ok"
    return "missing"


def _mint_amount(balances, owner, mint):
    total = 0
    seen = False
    for row in balances or []:
        if not isinstance(row, dict) or row.get("mint") != mint or row.get("owner") != owner:
            continue
        seen = True
        try:
            total += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return total, seen


def signature_matches_order(order, tx, owner):
    """The confirmed transaction has to move this order's mint for the linked wallet."""
    if not isinstance(tx, dict) or not owner or not (order or {}).get("mint"):
        return False
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return False
    mint = order["mint"]
    pre, pre_seen = _mint_amount(meta.get("preTokenBalances"), owner, mint)
    post, post_seen = _mint_amount(meta.get("postTokenBalances"), owner, mint)
    if not pre_seen and not post_seen:
        return False
    if (order.get("side") or "buy") == "sell":
        return post < pre
    return post > pre


_LAB = {"at": 0.0, "ready": False, "why": "lab has not cleared live trading",
        "pause": False, "pause_why": "", "edges": []}


def _apply_lab_report(report):
    gate = (report or {}).get("readiness") or {}
    ready = bool(gate.get("ready"))
    regime = (report or {}).get("regime") or {}
    edges = (report or {}).get("edges") or []
    _LAB.update(
        at=time.time(),
        ready=ready,
        why="lab cleared this strategy" if ready else "lab has not cleared live trading",
        pause=bool(regime.get("pause")),
        pause_why=str(regime.get("why") or "")[:160],
        edges=[e for e in edges if isinstance(e, dict)],
    )


def _score_bucket(score):
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if score < 60:
        return "under 60"
    if score < 70:
        return "60–69"
    if score < 80:
        return "70–79"
    return "80+"


def lab_entry_block(score):
    """Why the lab says to skip a paper entry, or "". Without a lab report the desk trades as before."""
    if _LAB["pause"]:
        return "lab: market cold, " + _LAB["pause_why"]
    bucket = _score_bucket(score)
    for edge in _LAB["edges"]:
        if edge.get("bucket") == bucket and edge.get("pays") is False:
            return f"lab: score {bucket.replace('–', '-')} loses after costs"
    return ""


def lab_status(force=False):
    """Cached lab gate. A paper fill must not wait on the network; pass force from a click."""
    if force:
        url = os.getenv("LAB_URL", "").strip().rstrip("/")
        key = os.getenv("LAB_KEY", "").strip()
        report = None
        if url and key:
            try:
                req = urllib.request.Request(
                    url + "/api/report",
                    headers={"X-Lab-Key": key, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    report = json.loads(resp.read().decode())
            except Exception:
                report = None
        _apply_lab_report(report)
    return _LAB["ready"], _LAB["why"]


async def refresh_lab(session):
    """Background refresh. Failure closes the gate."""
    url = os.getenv("LAB_URL", "").strip().rstrip("/")
    key = os.getenv("LAB_KEY", "").strip()
    report = None
    if url and key and session is not None:
        try:
            async with session.get(
                url + "/api/report",
                headers={"X-Lab-Key": key, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    report = await resp.json(content_type=None)
        except Exception:
            report = None
    _apply_lab_report(report)


def active(trade_sol):
    """True when a live buy of this SOL size is still inside every guard."""
    data = _today(_load())
    if data.get("halted") or data.get("stuck_sell"):
        return False, data.get("reason") or "halted"
    ready, why = lab_status()
    if not ready:
        return False, why
    px = sol_price()
    if not px:
        return False, "no SOL price"
    usd = float(trade_sol) * px
    if usd > max_trade_usd() + 1e-6:
        return False, f"trade ${usd:.2f} is over the ${max_trade_usd():.0f} cap"
    reserve = float(ct.CFG.get("reserve_usd") or 0)
    exposure = float(data.get("exposure_usd") or 0)
    if exposure + usd + reserve > max_exposure_usd() + 1e-6:
        return False, "exposure plus reserve would pass the live cap"
    if float(data.get("daily_loss_usd") or 0) >= max_daily_loss_usd():
        return False, "daily loss limit"
    return True, "ok"


def queue_buy(mint, size_sol):
    ok, why = active(size_sol)
    if not ok:
        return False, why
    if not (os.getenv("LIVE_WALLET_KEY") or os.getenv("WALLET_PRIVATE_KEY")):
        return True, "allowed, no wallet key so nothing was sent"
    # A key is present, but this process still does not sign. The guard is the gate.
    return True, "allowed"


def _pin_hash(pin, salt):
    return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()


def check_lock(pin):
    """True only for the spend code. The code is stored as a hash."""
    data = _load()
    if not data.get("lock_hash"):
        return False, "Set a lock code before wallet trading."
    salt = data.get("lock_salt") or ""
    if _pin_hash(str(pin or "").strip(), salt) != data.get("lock_hash"):
        data["lock_fails"] = int(data.get("lock_fails") or 0) + 1
        if data["lock_fails"] >= 5:
            data["wallet_trade"] = False
            data["halted"] = True
            data["reason"] = "spend lock"
        _save(data)
        return False, "Wrong lock code." if data["lock_fails"] < 5 else "Spend lock shut after five wrong codes."
    if data.get("lock_fails"):
        data["lock_fails"] = 0
        _save(data)
    return True, "ok"


def set_lock(pin, old=""):
    """Set the spend code. Replacing it requires the current code."""
    pin = str(pin or "").strip()
    if not (4 <= len(pin) <= 64):
        return False, "Use a lock code of 4 to 64 characters."
    data = _load()
    if data.get("lock_hash"):
        ok, why = check_lock(old)
        if not ok:
            return False, why
        data = _load()
    salt = secrets.token_hex(16)
    data["lock_salt"] = salt
    data["lock_hash"] = _pin_hash(pin, salt)
    data["lock_fails"] = 0
    data["wallet_trade"] = False
    if data.get("reason") in ("", "paper mode", "spend lock"):
        data["halted"] = True
        data["reason"] = "paper mode"
    _save(data)
    return True, "ok"


def set_phantom(address, trade, pin=""):
    """Remember a public address. The private key never comes here."""
    address = "".join(str(address or "").split())
    if address and not (32 <= len(address) <= 44):
        return False, "That is not a Solana address."
    data = _load()
    data["phantom"] = address
    want = bool(trade) and bool(address)
    if want:
        ok, why = check_lock(pin)
        if not ok:
            return False, why
        ready, why = lab_status(force=True)
        if not ready:
            return False, why
        data = _load()
        data["phantom"] = address
        if data.get("halted") and data.get("reason") not in ("", "paper mode", "spend lock"):
            _save(data)
            return False, data.get("reason") or "halted"
        data["wallet_trade"] = True
        data["halted"] = False
        data["reason"] = ""
    else:
        data["wallet_trade"] = False
        if data.get("reason") in ("", "paper mode", "spend lock"):
            data["halted"] = True
            data["reason"] = "paper mode"
    _save(data)
    return True, "ok"


def queue_phantom(mint, symbol, usd):
    """Ask the open dashboard to have Phantom sign one buy. Nothing is broadcast here."""
    data = _today(_load())
    if not data.get("wallet_trade") or not data.get("phantom"):
        return False
    ready, _why = lab_status()
    if not ready:
        return False
    if data.get("halted") or data.get("stuck_sell"):
        return False
    try:
        usd = float(usd)
    except (TypeError, ValueError):
        return False
    usd = min(usd, max_trade_usd())
    if usd <= 0:
        return False
    exposure = float(data.get("exposure_usd") or 0)
    if exposure + usd > max_exposure_usd() + 1e-6:
        return False
    if float(data.get("daily_loss_usd") or 0) >= max_daily_loss_usd():
        return False
    orders = data.setdefault("orders", [])
    if any(o.get("mint") == mint and o.get("status") == "pending" for o in orders):
        return False
    orders.insert(0, {
        "id": str(int(time.time() * 1000)),
        "mint": mint,
        "symbol": str(symbol or "")[:24],
        "usd": round(usd, 2),
        "side": "buy",
        "status": "pending",
        "time": deskio.stamp(),
    })
    data["orders"] = orders[:20]
    data["exposure_usd"] = round(exposure + usd, 2)
    _save(data)
    return True


def queue_sell(mint, symbol, frac, why):
    """Ask Phantom to approve a sell at a ladder, stop, or rug exit. Nothing is broadcast here."""
    try:
        frac = float(frac)
    except (TypeError, ValueError):
        return False
    if frac <= 0:
        return False
    data = _today(_load())
    if not data.get("wallet_trade") or not data.get("phantom") or data.get("halted"):
        return False
    ready, _why = lab_status()
    if not ready:
        return False
    pos = next((p for p in data.get("positions") or [] if p.get("mint") == mint and float(p.get("left") or 0) > 0.01), None)
    if not pos:
        return False
    frac = min(frac, float(pos.get("left") or 0))
    orders = data.setdefault("orders", [])
    for order in orders:
        if order.get("mint") == mint and order.get("side") == "sell" and order.get("status") == "pending":
            order["frac"] = round(min(float(pos.get("left") or 0), float(order.get("frac") or 0) + frac), 4)
            order["why"] = str(why or "")[:80]
            _save(data)
            return True
    orders.insert(0, {
        "id": str(int(time.time() * 1000)),
        "mint": mint,
        "symbol": str(symbol or pos.get("symbol") or "")[:24],
        "usd": round(float(pos.get("usd") or 0) * frac, 2),
        "side": "sell",
        "frac": round(frac, 4),
        "why": str(why or "")[:80],
        "status": "pending",
        "time": deskio.stamp(),
    })
    data["orders"] = orders[:20]
    _save(data)
    return True


def _book_fill(data, order):
    side = order.get("side") or "buy"
    if side != "sell":
        data.setdefault("positions", []).append({
            "mint": order.get("mint"),
            "symbol": order.get("symbol") or "",
            "usd": float(order.get("usd") or 0),
            "left": 1.0,
        })
        return
    frac = float(order.get("frac") or 0)
    kept = []
    for pos in data.get("positions") or []:
        if pos.get("mint") != order.get("mint"):
            kept.append(pos)
            continue
        pos["left"] = max(0.0, float(pos.get("left") or 0) - frac)
        data["exposure_usd"] = round(
            max(0.0, float(data.get("exposure_usd") or 0) - float(pos.get("usd") or 0) * frac), 2
        )
        if pos["left"] > 0.01:
            kept.append(pos)
    data["positions"] = kept


def finish_order(order_id, signature="", error=""):
    data = _load()
    for order in data.get("orders") or []:
        if str(order.get("id")) != str(order_id) or order.get("status") != "pending":
            continue
        if error:
            order["status"] = "failed"
            order["error"] = str(error)[:160]
            if (order.get("side") or "buy") != "sell":
                data["exposure_usd"] = round(max(0.0, float(data.get("exposure_usd") or 0) - float(order.get("usd") or 0)), 2)
        else:
            signature = str(signature or "").strip()
            if not signature:
                return False
            order["status"] = "sent"
            order["signature"] = signature[:120]
            _book_fill(data, order)
        break
    data["orders"] = (data.get("orders") or [])[:20]
    _save(data)
    return True


def pending_order():
    data = _load()
    for order in data.get("orders") or []:
        if order.get("status") == "pending":
            return order
    return None


def public():
    data = _today(_load())
    ready, why = lab_status()
    return {
        "halted": bool(data.get("halted") or data.get("stuck_sell")),
        "reason": data.get("reason") or "",
        "max_trade_usd": max_trade_usd(),
        "max_exposure_usd": max_exposure_usd(),
        "daily_loss_usd": max_daily_loss_usd(),
        "daily_loss_now": round(float(data.get("daily_loss_usd") or 0), 2),
        "exposure_usd": round(float(data.get("exposure_usd") or 0), 2),
        "reserve_usd": float(ct.CFG.get("reserve_usd") or 0),
        "phantom": data.get("phantom") or "",
        "wallet_trade": bool(data.get("wallet_trade")) and not data.get("halted") and ready,
        "lab_ready": ready,
        "lab_reason": why,
        "locked": bool(data.get("lock_hash")),
        "orders": (data.get("orders") or [])[:8],
        "positions": [
            {"mint": p.get("mint"), "symbol": p.get("symbol") or "", "left": p.get("left")}
            for p in (data.get("positions") or [])[:8]
        ],
    }
