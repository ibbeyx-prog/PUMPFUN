"""
Paper-only skills. These are public meme-coin checks the agent applies
before a simulated entry. They do not place real orders.
"""
import json
import os
import time

DATA = os.getenv("DATA_DIR", ".")
PATH = os.path.join(DATA, "study.json")

# A 5-minute move above this is a late entry, not a fresh one.
CHASE_5M = 45
# Quoted market cap is not cash. The pool has to be deep enough to exit.
MIN_LIQ_OF_MCAP = 0.08
# The first minutes of a pump.fun launch are mostly the launch wallets.
SETTLE_MIN = 5
MAX_NEW = 1

SKILLS = [
    {
        "id": "no_chase",
        "name": "Don't chase the candle",
        "lesson": f"Skip a coin that is already up more than {CHASE_5M}% in 5 minutes. Late meme entries usually buy the top.",
        "source": "Public DEX practice: a vertical 5-minute candle is the usual losing entry.",
    },
    {
        "id": "depth",
        "name": "Need real liquidity",
        "lesson": f"Skip when the pool is under {MIN_LIQ_OF_MCAP:.0%} of market cap. The cap on the screen is not the size you can sell.",
        "source": "DEX exit risk: thin pools gap through a paper stop.",
    },
    {
        "id": "settle",
        "name": "Let the open settle",
        "lesson": f"Skip a coin younger than {SETTLE_MIN} minutes. The first prints are mostly the launch wallets.",
        "source": "Pump.fun launch flow: snipers and bundled buys dominate the open.",
    },
    {
        "id": "confirm",
        "name": "Two markets must agree",
        "lesson": "Skip a name that shows on only one feed. One venue can print a spike the others never trade.",
        "source": "Cross-check of pump.fun, DexScreener, GMGN, and Birdeye.",
    },
    {
        "id": "cut_fades",
        "name": "Cut trades that never work",
        "lesson": "If a paper trade is still weak after the early-cut wait, sell it. Most meme losers never reclaim the entry.",
        "source": "This book's closed trades, where most losses happened before 1x.",
    },
    {
        "id": "one_at_a_time",
        "name": "One new paper entry",
        "lesson": "Take at most one new paper position per scan. Buying every green name is how one bad hour wipes the book.",
        "source": "Position sizing for a 0.1 SOL paper size and a 5-position cap.",
    },
    {
        "id": "rugcheck",
        "name": "RugCheck before entry",
        "lesson": "Skip a danger report, a rugged flag, a RugCheck score of 50 or more, or a single wallet holding 35% or more.",
        "source": "RugCheck token report at rugcheck.xyz.",
    },
    {
        "id": "bubblemap",
        "name": "Bubblemap clusters",
        "lesson": "Skip when the biggest holder cluster is 20% or more of supply, the top 10 clustered wallets hold 55%, or the Bubblemaps score is under 40.",
        "source": "Bubblemaps holder map. Needs BUBBLEMAPS_API_KEY. The public map link still opens without it.",
    },
]


def _sources(c):
    return set(c.get("sources") or [])


def blocks(c):
    """Reasons to refuse a paper entry. Empty means the skills allow it."""
    reasons = []
    ch = c.get("change_5m")
    if ch is not None and ch > CHASE_5M:
        reasons.append(f"skill: don't chase a {ch:.0f}% 5m move")
    mcap, liq = c.get("mcap"), c.get("liq")
    if mcap and liq is not None and mcap > 0 and (liq / mcap) < MIN_LIQ_OF_MCAP:
        reasons.append("skill: liquidity under 8% of mcap")
    age = c.get("age_min")
    if age is not None and age < SETTLE_MIN:
        reasons.append("skill: younger than 5 minutes")
    if len(_sources(c)) < 2:
        reasons.append("skill: need a second market")
    return reasons


def _load():
    if not os.path.exists(PATH):
        return {}
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def observe(rows):
    """Remember what this scan's market looked like, so the dashboard can show the lesson."""
    rows = rows or []
    chase = sum(1 for r in rows if (r.get("change_5m") or 0) > CHASE_5M)
    thin = 0
    young = 0
    single = 0
    for r in rows:
        mcap, liq = r.get("mcap"), r.get("liq")
        if mcap and liq is not None and mcap > 0 and liq / mcap < MIN_LIQ_OF_MCAP:
            thin += 1
        if r.get("age_min") is not None and r["age_min"] < SETTLE_MIN:
            young += 1
        if len(r.get("sources") or []) < 2:
            single += 1
    rug_hits = sum(1 for r in rows if "rugcheck:" in (r.get("note") or ""))
    bubble_hits = sum(1 for r in rows if "bubblemap:" in (r.get("note") or ""))
    def bit(n, one, many):
        return f"{n} {one if n == 1 else many}"

    note = (
        f"Studied {bit(len(rows), 'name', 'names')} on this scan. "
        f"{bit(chase, 'had', 'had')} already run too far, "
        f"{bit(thin, 'was', 'were')} too thin to exit, "
        f"{bit(young, 'was', 'were')} under {SETTLE_MIN} minutes, and "
        f"{bit(single, 'showed', 'showed')} on only one market. "
        f"RugCheck blocked {rug_hits}. Bubblemap blocked {bubble_hits}. "
        "A paper buy still needs the score and a real SOL price."
    )
    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": note,
        "tape": {
            "names": len(rows),
            "chase": chase,
            "thin": thin,
            "young": young,
            "single": single,
        },
    }
    os.makedirs(DATA, exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def public():
    data = _load()
    return {
        "updated": data.get("updated"),
        "note": data.get("note") or "The first study runs on the next scan.",
        "tape": data.get("tape") or {},
        "skills": SKILLS,
    }


def summary():
    data = public()
    names = ", ".join(s["name"] for s in SKILLS)
    return f"{data['note']} Skills in use: {names}."
