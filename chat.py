"""
Dashboard chat. Answers from the paper agent's own trades, positions, and rules.
"""
import json
import os
import re
import time

import deskio

DATA = os.getenv("DATA_DIR", ".")
PATH = os.path.join(DATA, "chat.json")


def _load():
    if not os.path.exists(PATH):
        return []
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(rows):
    deskio.write_json(PATH, rows[-80:])


def history():
    return _load()[-40:]


def add(role, text):
    rows = _load()
    rows.append({"role": role, "text": text, "time": time.strftime("%H:%M")})
    _save(rows)
    return history()


def _hit(q, words):
    return any(w in q for w in words)


def _sol(n):
    if n is None:
        return "n/a"
    return f"{n:+.3f} SOL"


def _named(q, symbol):
    sym = (symbol or "").lower().strip()
    if len(sym) < 2:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(sym)}(?![a-z0-9])", q) is not None


def _about_symbol(q, ctx):
    for item in ctx.get("open") or []:
        if _named(q, item.get("symbol")):
            advice = (item.get("advice") or {}).get("text") or "No extra note."
            x = item.get("x")
            return (f"{item['symbol']} is open at {x:.2f}x, pnl {_sol(item.get('pnl'))}. "
                    f"{advice}") if x else f"{item['symbol']} is open. {advice}"
    for item in ctx.get("closed_rows") or []:
        if _named(q, item.get("symbol")):
            return (f"{item['symbol']} closed at {float(item.get('x') or 0):.2f}x, "
                    f"pnl {_sol(float(item.get('pnl') or 0))}. {item.get('note') or ''}")
    for item in ctx.get("cands") or []:
        if _named(q, item.get("symbol")):
            advice = (item.get("advice") or {}).get("text") or item.get("note") or ""
            return f"{item['symbol']} is a {item.get('decision')} at score {item.get('score')}. {advice}"
    return None


def answer(message, ctx):
    q = (message or "").lower().strip()
    if not q:
        return "Ask about PnL, open positions, the 24h report, rule changes, or a token."
    named = _about_symbol(q, ctx)
    if named and not _hit(q, ("pnl", "report", "rule", "help")):
        return named
    if _hit(q, ("help", "what can you", "commands")):
        return ("I can talk about paper results only. Ask how PnL looks, what's open, "
                "what I'd buy next, the latest 24h report, why a rule changed, or name a token.")
    if _hit(q, ("pnl", "profit", "loss", "how are", "doing", "result", "performance")):
        wr = ctx.get("win_rate")
        wr_s = "n/a" if wr is None else f"{wr:.0%}"
        return (f"Paper PnL is {_sol(ctx.get('pnl'))} from {ctx.get('closed')} closes, "
                f"win rate {wr_s}. {ctx.get('lesson') or ''}")
    if _hit(q, ("open", "position", "holding", "bag")):
        rows = ctx.get("open") or []
        if not rows:
            return "Nothing is open right now."
        bits = []
        for p in rows[:8]:
            advice = (p.get("advice") or {}).get("label") or "Hold"
            x = p.get("x")
            bits.append(f"{p.get('symbol') or p['mint'][:4]} {x:.2f}x {advice}" if x else f"{p.get('symbol')} {advice}")
        return "Open: " + "; ".join(bits) + "."
    if _hit(q, ("report", "24h", "24 h", "daily", "today")):
        report = ctx.get("report")
        if not report:
            return f"No 24h report yet. The next one is at {ctx.get('next_report') or 'the end of the first day'}."
        return f"{report.get('start')} to {report.get('end')}: {report.get('text')}"
    if _hit(q, ("skill", "learn", "educat", "studied", "study", "meme")):
        return ctx.get("skills_text") or "I use public meme-coin checks: don't chase, need liquidity, let the open settle, and require two markets."
    if _hit(q, ("rule", "change", "setting", "why did you", "tune")):
        changes = ctx.get("changes") or []
        if not changes:
            return "I have not edited any rules yet."
        bits = [f"{c.get('what')} {c.get('from') or 'default'} -> {c.get('to')} ({c.get('why')})" for c in changes[:4]]
        values = ctx.get("rules") or {}
        live = ", ".join(f"{k} {v}" for k, v in values.items()) or "defaults"
        return "Current rules: " + live + ". Latest edits: " + " | ".join(bits)
    if _hit(q, ("next", "buy", "enter", "watch", "recommend", "suggest", "take")):
        cands = [c for c in (ctx.get("cands") or []) if (c.get("advice") or {}).get("label") in ("Take", "Small")]
        if not cands:
            return "Nothing I would buy right now. Most names are a pass or a wait."
        bits = []
        for c in cands[:4]:
            label = (c.get("advice") or {}).get("label") or c.get("decision")
            bits.append(f"{c.get('symbol')} {label}")
        return "I'd look at " + ", ".join(bits) + ". I still only paper-trade, and only when the rules pass."
    if named:
        return named
    return (f"Scanner is {ctx.get('phase') or 'idle'}. Paper PnL {_sol(ctx.get('pnl'))}, "
            f"{len(ctx.get('open') or [])} open. Ask about positions, the 24h report, or a token name.")
