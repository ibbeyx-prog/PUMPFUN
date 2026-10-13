"""
Replay engine for Paper Scanner Lab.

Takes the recorded candidate stream + price paths and answers, with numbers:
  1. Do scores / sources / skip rules actually predict outcomes?  (outcomes())
  2. Which rule preset or exit style does best on the SAME signals? (shadow books)
  3. Does the strategy beat random entries from the same list?     (random baseline)
  4. Is the result distinguishable from luck at this sample size?  (bootstrap CI)
  5. Why did the desk's real paper trades lose?                    (postmortem())

Everything is pure Python (stdlib only). Fills are deliberately harsher than the
desk's flat 3% slippage + 0.002 SOL fee: slippage grows with trade size / liquidity,
a platform fee applies on both sides, entry happens a delay after the signal, and a
token that vanishes from the market is treated as a ~90% loss.
"""
import json, random, re, statistics, time
from dataclasses import dataclass, replace

CONFIRM = {"gmgn", "dexscreener", "birdeye"}
HORIZON = 4 * 3600


# ───────────────────────── models ─────────────────────────
@dataclass
class Fill:
    base_slip: float = 0.03
    impact_k: float = 2.0          # constant-product impact ~ 2 * trade / total liquidity
    fee_pct: float = 0.01          # platform fee, each side
    fixed_fee_usd: float = 0.20    # priority fee / tip per transaction

    def slip(self, usd, liq):
        return self.base_slip + self.impact_k * usd / max(liq or 0.0, 2000.0)


ZERO_COST = Fill(0, 0, 0, 0)


@dataclass
class Strategy:
    name: str
    min_score: float = 0
    min_sources: int = 0
    max_change_5m: float = 1e9
    decisions: tuple = ("enter",)
    confirm: bool = True
    ladder: tuple = ((2.0, 0.40), (3.5, 0.30), (5.0, 1.0))   # (multiple, fraction of ORIGINAL)
    runner: tuple = None               # (first_x, first_frac, trail) - overrides ladder
    stop: float = 0.35
    stop_polls: int = 2
    time_stop_min: float = 90
    time_stop_x: float = 2.0
    early_cut_x: float = None
    early_cut_min: float = None
    liq_exit_drop: float = None        # sell if liquidity falls this fraction from entry
    max_open: int = 4
    one_per_bucket: bool = True        # at most one new entry per 45s scan
    entry_delay_s: float = 45
    trade_usd: float = 10.0


def default_strategies():
    desk = Strategy("desk-as-is")
    presets = [(3, 70, 45, .80, 10), (3, 80, 40, .75, 8), (2, 75, 55, .85, 12), (3, 65, 60, .80, 15)]
    out = [desk]
    for i, (ms, es, mc, ecx, ecm) in enumerate(presets, 1):
        out.append(Strategy(f"grind-{i}", min_score=es, min_sources=ms, max_change_5m=mc,
                            decisions=("enter", "watch"), early_cut_x=ecx, early_cut_min=ecm))
    b = out[1]
    runner = (2.0, 0.5, 0.30)
    out += [replace(b, name="grind-1 + runner", runner=runner, ladder=()),
            replace(b, name="grind-1 + liquidity exit", liq_exit_drop=0.5),
            replace(b, name="grind-1 + runner + liq exit", runner=runner, ladder=(), liq_exit_drop=0.5),
            replace(b, name="grind-1 + wide stop (50%)", stop=0.50)]
    return out


# ───────────────────────── data ─────────────────────────
def load_dataset(con):
    ds = {}
    for r in con.execute("SELECT mint, ts, symbol, score, decision, note, sources, change_5m, liq, price_sol "
                         "FROM candidates ORDER BY ts"):
        try:
            src = json.loads(r[6]) if r[6] else []
        except Exception:
            src = []
        d = ds.setdefault(r[0], {"obs": [], "path": []})
        d["obs"].append({"ts": r[1], "symbol": r[2] or "", "score": r[3] or 0, "decision": r[4] or "",
                         "note": r[5] or "", "sources": src, "change_5m": r[7], "liq": r[8], "price": r[9]})
    for r in con.execute("SELECT mint, ts, price_sol, liq_usd, ok FROM prices ORDER BY ts"):
        if r[0] in ds:
            ds[r[0]]["path"].append((r[1], r[2], r[3], r[4]))
    return ds


# ───────────────────────── simulation ─────────────────────────
def qualifies(o, S):
    if o["decision"] not in S.decisions or (o["score"] or 0) < S.min_score:
        return False
    src = {str(x).lower() for x in o["sources"]}
    if len(src) < S.min_sources or (S.confirm and not (src & CONFIRM)):
        return False
    c5 = o.get("change_5m")
    return not (c5 is not None and c5 > S.max_change_5m)


def simulate_trade(path, t_sig, S, F):
    i0 = next((i for i, p in enumerate(path) if p[0] >= t_sig + S.entry_delay_s and p[3] and p[1]), None)
    if i0 is None:
        return None
    ts0, p0, liq0, _ = path[i0]
    entry = p0 * (1 + F.slip(S.trade_usd, liq0))
    cost = S.trade_usd * (1 + F.fee_pct) + F.fixed_fee_usd
    st = {"left": 1.0, "got": 0.0}
    last = {"ts": ts0, "price": p0, "liq": liq0}

    def sell(frac, price, liq):
        frac = min(frac, st["left"])
        if frac <= 0:
            return
        usd = S.trade_usd * frac * (price / entry)
        st["got"] += usd * (1 - F.slip(usd, liq)) * (1 - F.fee_pct) - F.fixed_fee_usd
        st["left"] -= frac

    tier, below, dead, peak, runner_peak, reason = 0, 0, 0, 1.0, 1.0, "horizon"
    for ts, price, liq, ok in path[i0 + 1:]:
        if not ok or not price:
            dead += 1
            if dead >= 3:
                sell(st["left"], last["price"] * 0.1, 0)
                reason = "dead token"
                last["ts"] = ts
                break
            continue
        dead = 0
        last = {"ts": ts, "price": price, "liq": liq}
        x = price / entry
        peak = max(peak, x)
        age = (ts - ts0) / 60
        if S.liq_exit_drop and liq0 and liq is not None and liq <= liq0 * (1 - S.liq_exit_drop):
            sell(st["left"], price, liq); reason = "liquidity pulled"; break
        below = below + 1 if x <= 1 - S.stop else 0
        if below >= S.stop_polls and tier == 0:
            sell(st["left"], price, liq); reason = "stop"; break
        if tier == 0 and S.early_cut_x and age >= S.early_cut_min and x < S.early_cut_x:
            sell(st["left"], price, liq); reason = "early cut"; break
        if tier == 0 and age >= S.time_stop_min and x < S.time_stop_x:
            sell(st["left"], price, liq); reason = "time stop"; break
        if S.runner:
            fx, ff, trail = S.runner
            if tier == 0 and x >= fx:
                sell(ff, price, liq); tier = 1; runner_peak = x
            elif tier == 1:
                runner_peak = max(runner_peak, x)
                if x <= runner_peak * (1 - trail):
                    sell(st["left"], price, liq); reason = "trailing stop"; break
        else:
            while tier < len(S.ladder) and x >= S.ladder[tier][0]:
                _, fr = S.ladder[tier]
                sell(st["left"] if fr >= 1 else fr, price, liq)
                tier += 1
                reason = f"ladder {S.ladder[tier - 1][0]}x"
                if st["left"] <= 1e-9:
                    break
            if st["left"] <= 1e-9:
                break
    if st["left"] > 1e-9:
        sell(st["left"], last["price"], last["liq"])
    pnl = st["got"] - cost
    return {"entry_ts": ts0, "exit_ts": last["ts"], "ret": pnl / cost, "pnl_usd": pnl,
            "peak_x": peak, "reason": reason}


def run_strategy(ds, S, F):
    sig = []
    for mint, d in ds.items():
        for o in d["obs"]:
            if qualifies(o, S):
                sig.append((o["ts"], o["score"], mint, o))
                break
    if S.one_per_bucket:
        best = {}
        for s in sig:
            b = int(s[0] // 45)
            if b not in best or s[1] > best[b][1]:
                best[b] = s
        sig = list(best.values())
    sig.sort(key=lambda s: s[0])
    trades, open_exits = [], []
    for ts, _, mint, o in sig:
        t = simulate_trade(ds[mint]["path"], ts, S, F)
        if not t:
            continue
        open_exits = [e for e in open_exits if e > t["entry_ts"]]
        if len(open_exits) >= S.max_open:
            continue
        open_exits.append(t["exit_ts"])
        trades.append({**t, "mint": mint, "symbol": o["symbol"], "score": o["score"]})
    return trades


# ───────────────────────── statistics ─────────────────────────
def bootstrap_ci(xs, iters=1000, seed=3):
    rnd = random.Random(seed)
    n = len(xs)
    means = sorted(statistics.fmean(rnd.choices(xs, k=n)) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def summarize(trades):
    rets = [t["ret"] for t in trades]
    n = len(rets)
    if n == 0:
        return {"n": 0, "verdict": "no trades"}
    wins = sum(r for r in rets if r > 0)
    losses = -sum(r for r in rets if r <= 0)
    cum = peak = dd = 0.0
    for t in sorted(trades, key=lambda t: t["exit_ts"]):
        cum += t["pnl_usd"]
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    lo, hi = bootstrap_ci(rets) if n >= 5 else (None, None)
    if n < 30:
        verdict = "too few trades to judge"
    elif lo > 0:
        verdict = "positive after costs (95% CI above 0)"
    elif hi < 0:
        verdict = "negative after costs (95% CI below 0)"
    else:
        verdict = "not distinguishable from zero"
    if n < 100 and n >= 30:
        verdict += " - still early (<100)"
    return {"n": n, "win_rate": sum(r > 0 for r in rets) / n, "mean": statistics.fmean(rets),
            "median": statistics.median(rets), "profit_factor": (wins / losses) if losses > 0 else None,
            "max_dd_usd": dd, "total_usd": cum, "ci": (lo, hi), "verdict": verdict}


def random_baseline(ds, S, F, k, iters=300, seed=7):
    """Mean return of k RANDOM entries from the same candidate list, same exits."""
    U = replace(S, min_score=0, min_sources=0, max_change_5m=1e9, decisions=("enter", "watch"),
                one_per_bucket=False, max_open=10 ** 9, early_cut_x=S.early_cut_x)
    uni = [t["ret"] for t in run_strategy(ds, U, F)]
    if len(uni) < max(k, 10) or k < 3:
        return None
    rnd = random.Random(seed)
    return sorted(statistics.fmean(rnd.sample(uni, k)) for _ in range(iters))


def percentile_vs_random(mean, draws):
    return sum(d < mean for d in draws) / len(draws) if draws else None


# ───────────────────────── candidate outcomes ─────────────────────────
def note_class(note):
    first = re.split(r"[;·|,]", note or "")[0].strip().lower()
    return re.sub(r"[\d.,$%+x]+", "n", first)[:40] or "(no note)"


def outcomes(ds):
    rows = []
    for mint, d in ds.items():
        pts = [p for p in d["path"] if p[3] and p[1]]
        if len(pts) < 3:
            continue
        t0, p0, liq0, _ = pts[0]

        def x_at(sec):
            c = [p for p in pts if p[0] <= t0 + sec]
            return c[-1][1] / p0 if c else None
        hit = None
        for p in pts[1:]:
            x = p[1] / p0
            if x >= 2:
                hit = True; break
            if x <= 0.65:
                hit = False; break
        rug = any(liq0 and p[2] is not None and p[2] <= 0.3 * liq0 for p in pts) or \
            any(d["path"][i][3] == 0 and d["path"][i + 1][3] == 0 and d["path"][i + 2][3] == 0
                for i in range(len(d["path"]) - 2))
        o = d["obs"][0]
        rows.append({"decision": o["decision"], "score": o["score"], "n_src": len(o["sources"]),
                     "skip": note_class(o["note"]) if o["decision"] == "skip" else None,
                     "x15": x_at(900), "x1h": x_at(3600), "x4h": x_at(HORIZON),
                     "peak": max(p[1] for p in pts) / p0, "hit2": bool(hit), "rug": rug})
    return rows


def group_table(rows, keyfn, min_n=1):
    g = {}
    for r in rows:
        k = keyfn(r)
        if k is not None:
            g.setdefault(k, []).append(r)
    out = []
    for k, rs in g.items():
        if len(rs) < min_n:
            continue
        x1 = [r["x1h"] for r in rs if r["x1h"] is not None]
        out.append({"group": str(k), "n": len(rs), "hit2": sum(r["hit2"] for r in rs) / len(rs),
                    "rug": sum(r["rug"] for r in rs) / len(rs),
                    "med_x1h": statistics.median(x1) if x1 else None})
    return sorted(out, key=lambda r: -r["n"])


def bucket_score(s):
    return "<60" if s < 60 else "60-69" if s < 70 else "70-79" if s < 80 else "80+"


# ───────────────────────── post-mortem of the desk's real trades ─────────────────────────
def postmortem(ledger, ds, tz_offset_h=0.0):
    def ts(s):
        return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S")) - tz_offset_h * 3600
    buys = {}
    for r in sorted(ledger, key=lambda r: r["time"]):
        if r["event"] == "BUY":
            buys[r["mint"]] = ts(r["time"])
    tags = {}
    for r in ledger:
        if r["event"] != "CLOSED" or r["mint"] not in ds:
            continue
        pnl = float(r.get("sol_pnl") or 0)
        t_buy, t_close = buys.get(r["mint"]), ts(r["time"])
        pts = [p for p in ds[r["mint"]]["path"] if p[3] and p[1]]
        seg = [p for p in pts if t_buy and t_buy <= p[0] <= t_close]
        after = [p for p in pts if p[0] > t_close]
        if len(seg) < 2:
            tag = "no price data"
        else:
            p0, liq0 = seg[0][1], seg[0][2]
            peak = max(p[1] for p in seg) / p0
            if liq0 and any(p[2] is not None and p[2] <= 0.3 * liq0 for p in seg):
                tag = "rug or liquidity pull"
            elif pnl > 0:
                tag = "sold too early" if after and max(p[1] for p in after) / seg[-1][1] >= 1.5 else "took profit ok"
            elif peak >= 1.5:
                tag = "gave back gains"
            elif "time" in (r.get("note") or "").lower():
                tag = "stalled until time stop"
            else:
                tag = "slow bleed"
        tags[tag] = tags.get(tag, 0) + 1
    return tags


# ───────────────────────── report ─────────────────────────
def build_report(con, ledger=None, tz_offset_h=0.0, strategies=None):
    ds = load_dataset(con)
    F = Fill()
    outs = outcomes(ds)
    t_first = min((d["obs"][0]["ts"] for d in ds.values()), default=None)
    complete = sum(1 for d in ds.values() if d["path"] and d["path"][-1][0] - d["obs"][0]["ts"] >= HORIZON - 600)
    rep = {"generated": time.strftime("%F %T"), "mints": len(ds), "complete_4h": complete,
           "hours_of_data": round((time.time() - t_first) / 3600, 1) if t_first else 0,
           "warnings": [], "strategies": [], "outcomes": {}}
    if len(outs) < 100:
        rep["warnings"].append(f"Only {len(outs)} tracked coins have usable price paths. "
                               "Treat every number below as a hint; wait for 300+.")
    rep["outcomes"] = {
        "by_decision": group_table(outs, lambda r: r["decision"]),
        "by_score": group_table(outs, lambda r: bucket_score(r["score"])),
        "by_sources": group_table(outs, lambda r: r["n_src"]),
        "by_skip_reason": group_table(outs, lambda r: r["skip"], min_n=3),
        "base_rate": {"hit2": sum(r["hit2"] for r in outs) / len(outs) if outs else None,
                      "rug": sum(r["rug"] for r in outs) / len(outs) if outs else None}}
    for S in strategies or default_strategies():
        tr = run_strategy(ds, S, F)
        s = summarize(tr)
        s["name"] = S.name
        free = replace(S, max_open=10 ** 9, one_per_bucket=False)       # same signals, no overlap limits
        a, b = run_strategy(ds, free, ZERO_COST), run_strategy(ds, free, F)
        s["cost_drag"] = (statistics.fmean(t["ret"] for t in a) - statistics.fmean(t["ret"] for t in b)) if a and b else None
        draws = random_baseline(ds, S, F, len(tr)) if tr else None
        s["vs_random_pct"] = percentile_vs_random(s["mean"], draws) if draws and s["n"] else None
        s["exits"] = {}
        for t in tr:
            s["exits"][t["reason"]] = s["exits"].get(t["reason"], 0) + 1
        rep["strategies"].append(s)
    if ledger:
        closed = [r for r in ledger if r["event"] == "CLOSED"]
        rep["desk"] = {"closed": len(closed),
                       "win_rate": (sum(float(r.get("sol_pnl") or 0) > 0 for r in closed) / len(closed)) if closed else None,
                       "sol_pnl": sum(float(r.get("sol_pnl") or 0) for r in closed),
                       "postmortem": postmortem(ledger, ds, tz_offset_h)}
    return rep


def _pct(x, d=1):
    return "-" if x is None else f"{x * 100:.{d}f}%"


def to_markdown(rep):
    L = [f"# Paper Scanner Lab report ({rep['generated']})", "",
         f"Tracked coins: {rep['mints']} ({rep['complete_4h']} with a full 4h price path), "
         f"{rep['hours_of_data']}h of data.", ""]
    for w in rep["warnings"]:
        L.append(f"> WARNING: {w}")
    L += ["", "## Do the desk's signals predict anything?",
          f"Base rate: {_pct(rep['outcomes']['base_rate']['hit2'])} of tracked coins hit 2x before -35%; "
          f"{_pct(rep['outcomes']['base_rate']['rug'])} look rugged.", ""]
    for key, title in [("by_decision", "By decision"), ("by_score", "By score"),
                       ("by_sources", "By number of sources"), ("by_skip_reason", "By skip reason (3+ coins)")]:
        L += [f"**{title}**", "", "| group | n | hit 2x | rugged | median x at 1h |", "|---|---|---|---|---|"]
        for r in rep["outcomes"][key]:
            L.append(f"| {r['group']} | {r['n']} | {_pct(r['hit2'])} | {_pct(r['rug'])} | "
                     f"{'-' if r['med_x1h'] is None else format(r['med_x1h'], '.2f') + 'x'} |")
        L.append("")
    L += ["## Shadow books (same signals, harsher realistic fills)", "",
          "| strategy | n | win | mean/trade | 95% CI | profit factor | beats random | verdict |",
          "|---|---|---|---|---|---|---|---|"]
    for s in rep["strategies"]:
        if not s["n"]:
            L.append(f"| {s['name']} | 0 | - | - | - | - | - | no trades |")
            continue
        ci = "-" if s["ci"][0] is None else f"{_pct(s['ci'][0])} to {_pct(s['ci'][1])}"
        pf = "-" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
        L.append(f"| {s['name']} | {s['n']} | {_pct(s['win_rate'], 0)} | {_pct(s['mean'])} | {ci} | {pf} | "
                 f"{_pct(s['vs_random_pct'], 0)} | {s['verdict']} |")
    drags = [x["cost_drag"] for x in rep["strategies"] if x.get("cost_drag") is not None]
    if drags:
        L += ["", f"Realistic fills cost about {_pct(statistics.fmean(drags))} of each trade versus a free fill "
                  "(slippage that grows with size/liquidity, 1% fee each side, $0.20 per transaction, 45s entry delay)."]
    if rep.get("desk"):
        d = rep["desk"]
        L += ["", "## The desk's own closed paper trades",
              f"Closed {d['closed']}, win rate {_pct(d['win_rate'], 0)}, SOL PnL {d['sol_pnl']:+.3f}.",
              "Why trades ended: " + (", ".join(f"{k} {v}" for k, v in d["postmortem"].items()) or "no data yet")]
    if rep.get("hypotheses"):
        L += ["", "## Hypotheses to test (AI-written, NOT facts)", rep["hypotheses"]]
    return "\n".join(L)


def to_html(rep):
    md = to_markdown(rep)
    import html
    body, rows, in_table = [], [], False
    for line in md.split("\n"):
        if line.startswith("|"):
            if not in_table:
                body.append("<table>"); in_table = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            tag = "th" if not rows else "td"
            rows.append(1)
            body.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>"); in_table = False; rows = []
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith(">"):
            body.append(f"<p class=w>{html.escape(line[1:])}</p>")
        elif line.strip():
            body.append(f"<p>{html.escape(line).replace('**', '')}</p>")
    if in_table:
        body.append("</table>")
    css = ("body{background:#020617;color:#e2e8f0;font:14px system-ui;max-width:1000px;margin:0 auto;padding:16px}"
           "h1{font-size:20px}h2{font-size:16px;margin-top:28px}table{border-collapse:collapse;width:100%;margin:8px 0;"
           "display:block;overflow-x:auto}th,td{border-bottom:1px solid #1e293b;padding:6px 10px;text-align:left;"
           "white-space:nowrap}th{color:#94a3b8;font-weight:500}.w{color:#fbbf24}")
    return f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><style>{css}</style>" + "".join(body)
