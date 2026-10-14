"""
Cost parity: the lab's fill math against the desk's own copytrader.Paper on the same fills.

Run from anywhere in the repo: python paper-scanner-lab/parity_check.py
It writes only to a temporary DATA_DIR and makes no network calls. Passes when every case
agrees within $0.01 and round_trip_cost_usd matches for every ticket and pool.

The desk ledger keeps no pool size, SOL price, or fraction per sell, so a replay of the real
ledger cannot be exact. This check drives the same code path the ledger came from instead.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="parity-")
os.chdir(ROOT)
sys.path[:0] = [ROOT, HERE]

import copytrader as ct  # noqa: E402
import engine  # noqa: E402

SOL_USD = 150.0
TOLERANCE = 0.01
# ticket USD, pool USD, entry price USD, exits as (price USD, fraction of the original size)
CASES = [
    (5.5, 10000, 1.0, [(2.0, 0.5), (3.5, 0.25), (0.9, 0.25)]),
    (5.5, 0, 1.0, [(0.5, 1.0)]),
    (8.0, 25000, 2e-5, [(5e-5, 1.0)]),
    (12.0, 9000, 1.0, [(1.1, 1.0)]),
    (5.5, 50, 1.0, [(1.5, 1.0)]),
    (5.5, 20000, 1.0, [(0.3, 1.0)]),
]


def lab_pnl_usd(ticket, liq, entry_usd, exits):
    total = sum(engine.entry_parts(ticket).values())
    for px, frac in exits:
        total += sum(engine.piece_parts(entry_usd, px, ticket, frac, liq).values())
    return total


def closed_pnl_usd(i, ticket, liq, entry_usd, exits):
    """The desk's own position total, read from the CLOSED row it writes."""
    paper = ct.Paper()
    paper.bank = None
    mint = f"Closed{i}pump"
    paper.open(mint, "wallet", entry_usd / SOL_USD, size_sol=ticket / SOL_USD,
               liq_usd=liq, trade_usd=ticket, sol_px=SOL_USD)
    pnl = None
    for px, frac in exits:
        p = paper.pos[mint]
        paper.sell(mint, px / SOL_USD, frac, "parity", liq_usd=liq, sol_px=SOL_USD)
        if mint not in paper.pos:
            pnl = p["pnl"]
    return None if pnl is None else pnl * SOL_USD


def main():
    failed = 0
    for ticket in engine.TICKETS:
        for liq in (0, 5000, 10000, 50000):
            desk, lab = ct.round_trip_cost_usd(ticket, liq), engine.round_trip_cost_usd(ticket, liq)
            ok = desk == lab
            failed += not ok
            print(f"round trip ${ticket:g} pool {liq}: desk {desk} lab {lab} {'ok' if ok else 'MISMATCH'}")
    desk, lab = ct.round_trip_cost_usd(5.5, 10000), engine.round_trip_cost_usd(5.5, 10000)
    if not (desk == lab == 0.85):
        failed += 1
        print(f"round_trip_cost_usd(5.5, 10000): desk {desk} lab {lab}, expected 0.85")
    for i, (ticket, liq, entry_usd, exits) in enumerate(CASES):
        desk = closed_pnl_usd(i, ticket, liq, entry_usd, exits)
        lab = lab_pnl_usd(ticket, liq, entry_usd, exits)
        diff = abs(desk - lab)
        ok = diff <= TOLERANCE
        failed += not ok
        print(f"case {i}: ${ticket:g} pool {liq}: desk {desk:+.4f} lab {lab:+.4f} diff {diff:.4f} {'ok' if ok else 'MISMATCH'}")
    print("parity ok" if not failed else f"parity FAILED ({failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
