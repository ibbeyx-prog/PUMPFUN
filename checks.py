"""
RugCheck and Bubblemaps reads for paper entries. No orders are sent.
The public map is https://v2.bubblemaps.io/map?address=<mint>&chain=solana.
Cluster scores from that map need BUBBLEMAPS_API_KEY. RugCheck does not.
"""
import os
import time

import copytrader as ct

RUG = "https://api.rugcheck.xyz/v1/tokens"
BUBBLE = "https://api.bubblemaps.io/v0/tokens/metrics/solana"
MAP = "https://v2.bubblemaps.io/map"


def map_url(address, chain="solana"):
    """Public map. address is the coin mint. chain is the launch chain, solana for pump.fun."""
    if chain in ("sol", "", None):
        chain = "solana"
    return f"{MAP}?address={address}&chain={chain}"

# RugCheck normalised score. Higher means more risk. A clean pump coin sits near 1.
RUG_SKIP = 50
# One wallet above this share can dump the paper entry.
HOLDER_SKIP = 35
# Bubblemaps bundles is a 0-1 share of supply sitting in the top clusters.
CLUSTER_SKIP = 0.20
# Bubblemaps score runs 0 (concentrated) to 100 (spread out).
BUBBLE_SKIP = 40

_cache = {}


def bubble_key():
    return os.getenv("BUBBLEMAPS_API_KEY") or ct.CFG.get("bubblemaps_api_key") or ""


def _hit(kind, mint, ttl):
    row = _cache.get((kind, mint))
    if not row:
        return None
    if time.time() - row[0] > ttl:
        return None
    return row[1]


def _store(kind, mint, value, ttl_ok=600):
    _cache[(kind, mint)] = (time.time(), value)
    return value


async def rugcheck(session, mint):
    cached = _hit("rug", mint, 600)
    if cached is not None:
        return cached
    data = await ct.get_json(session, f"{RUG}/{mint}/report")
    if not isinstance(data, dict):
        return _store("rug", mint, {"ok": False, "label": "no report"})
    dangers = []
    for risk in data.get("risks") or []:
        if (risk.get("level") or "").lower() == "danger" and risk.get("name"):
            dangers.append(str(risk["name"])[:48])
    holders = data.get("topHolders") or []
    pcts = []
    for holder in holders:
        try:
            pcts.append(float(holder.get("pct")))
        except (TypeError, ValueError):
            continue
    out = {
        "ok": True,
        "score": data.get("score_normalised"),
        "rugged": bool(data.get("rugged")),
        "dangers": dangers[:3],
        "holder_pct": max(pcts) if pcts else None,
        "label": dangers[0] if dangers else ("rugged" if data.get("rugged") else "clean"),
    }
    return _store("rug", mint, out)


async def bubblemap(session, mint):
    key = bubble_key()
    if not key:
        return {"ok": False, "label": "needs key"}
    cached = _hit("bubble", mint, 600)
    if cached is not None:
        return cached
    data = await ct.get_json(
        session,
        f"{BUBBLE}/{mint}",
        {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "X-ApiKey": key},
    )
    if not isinstance(data, dict):
        return _store("bubble", mint, {"ok": False, "label": "no map"})
    stats = data.get("supply_stats") or {}
    scores = data.get("scores") or {}
    out = {
        "ok": True,
        "score": scores.get("bubblemaps_score"),
        "cluster": stats.get("bundles"),
        "top10": stats.get("top_10_adjusted"),
        "label": "mapped",
    }
    return _store("bubble", mint, out)


def apply(c, rug, bubble):
    """Copy a check onto the candidate the scorer already holds."""
    if rug and rug.get("ok"):
        c["rug_score"] = rug.get("score")
        c["rugged"] = rug.get("rugged")
        c["rug_dangers"] = rug.get("dangers") or []
        c["holder_pct"] = rug.get("holder_pct")
        c["rug_label"] = rug.get("label") or ""
    elif rug:
        c["rug_label"] = rug.get("label") or ""
    if bubble and bubble.get("ok"):
        c["bubble_score"] = bubble.get("score")
        c["bubble_cluster"] = bubble.get("cluster")
        c["bubble_top10"] = bubble.get("top10")
        c["bubble_label"] = bubble.get("label") or ""
    elif bubble:
        c["bubble_label"] = bubble.get("label") or ""


def blocks(c):
    reasons = []
    if c.get("rugged"):
        reasons.append("rugcheck: rugged")
    for name in c.get("rug_dangers") or []:
        reasons.append(f"rugcheck: {name}")
    score = c.get("rug_score")
    if score is not None and float(score) >= RUG_SKIP and not reasons:
        reasons.append(f"rugcheck: score {float(score):.0f}")
    pct = c.get("holder_pct")
    if pct is not None and float(pct) >= HOLDER_SKIP:
        reasons.append(f"rugcheck: top holder {float(pct):.0f}%")
    cluster = c.get("bubble_cluster")
    if cluster is not None and float(cluster) >= CLUSTER_SKIP:
        reasons.append(f"bubblemap: cluster {float(cluster):.0%}")
    top10 = c.get("bubble_top10")
    if top10 is not None and float(top10) >= 0.55:
        reasons.append(f"bubblemap: top 10 hold {float(top10):.0%}")
    bscore = c.get("bubble_score")
    if bscore is not None and float(bscore) < BUBBLE_SKIP:
        reasons.append(f"bubblemap: score {float(bscore):.0f}")
    return reasons
