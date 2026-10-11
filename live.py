"""
Guards for real-money execution. Eye may halt this, never resume it.

Nothing is signed or broadcast unless a wallet key is present, and even then
the order is refused when a USD limit, the reserve, or a halt says no.
Paper mode does not need this module's key.
"""
import json
import os
import time

import copytrader as ct

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
    return data


def _save(data):
    os.makedirs(ct.DATA, exist_ok=True)
    with open(HALT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def sol_price():
    return ct._SOL.get("price") or 0


def _today(data):
    day = time.strftime("%F")
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
    """Stop live trading. There is no resume for the agent."""
    data = _load()
    data["halted"] = True
    data["reason"] = str(reason)[:160]
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


def active(trade_sol):
    """True when a live buy of this SOL size is still inside every guard."""
    data = _today(_load())
    if data.get("halted") or data.get("stuck_sell"):
        return False, data.get("reason") or "halted"
    if paper_profit_sol() <= 0:
        return False, "paper book is not profitable"
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


def public():
    data = _today(_load())
    return {
        "halted": bool(data.get("halted") or data.get("stuck_sell")),
        "reason": data.get("reason") or "",
        "max_trade_usd": max_trade_usd(),
        "max_exposure_usd": max_exposure_usd(),
        "daily_loss_usd": max_daily_loss_usd(),
        "daily_loss_now": round(float(data.get("daily_loss_usd") or 0), 2),
        "exposure_usd": round(float(data.get("exposure_usd") or 0), 2),
        "reserve_usd": float(ct.CFG.get("reserve_usd") or 0),
    }
