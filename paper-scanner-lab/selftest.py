"""Engine checks on a synthetic market. No network and no desk files."""
import os
import tempfile

import engine
import lab


def snap(**extra):
    base = {
        "started_at": 0.0,
        "mint": "mint",
        "symbol": "TEST",
        "score": 75,
        "decision": "enter",
        "note": "3 sources, 5m 12%",
        "sources": ["gmgn", "dexscreener", "pump.fun"],
        "mcap": 50000,
        "liq": 20000,
        "change_5m": 12,
        "age_min": 30,
    }
    base.update(extra)
    return base


def path_from(points):
    """points are (minute, price) from t=0."""
    return [(minute * 60, price) for minute, price in points]


def rise_and_fade():
    """Entry near minute 1, a spike to 3x, then a fade through the early cut before the time stop."""
    points = []
    for minute in range(0, 241):
        if minute <= 2:
            price = 1.0
        elif minute <= 18:
            price = 1.0 + (minute - 2) * (2.0 / 16)
        else:
            price = max(0.45, 3.0 - (minute - 18) * 0.12)
        points.append((minute, price))
    return path_from(points)


def test_books_and_fills():
    assert len(engine.BOOKS) == 10
    harsh = engine.round_trip(1, 1, 5, 100)
    calm = engine.round_trip(1, 1, 5, 100000)
    assert harsh < calm < 0
    assert engine.vanished_pnl() < -4
    assert not engine.would_enter(engine.BOOKS[0], snap(note="rugcheck: rugged"))
    strict = next(book for book in engine.BOOKS if book.id == "strict-ladder")
    desk = next(book for book in engine.BOOKS if book.id == "desk-ladder")
    assert not engine.would_enter(strict, snap(score=75))
    assert engine.would_enter(desk, snap())
    gone = engine.simulate(desk, snap(), [])
    assert gone["reason"] == "vanished"
    path = rise_and_fade()
    ladder = engine.simulate(desk, snap(), path)
    cut = engine.simulate(next(book for book in engine.BOOKS if book.id == "desk-cut"), snap(), path)
    assert "ladder" in ladder["reason"] or ladder["pnl"] != cut["pnl"]
    assert cut["reason"] == "early-cut"
    assert ladder["pnl"] != cut["pnl"]
    runner = engine.simulate(next(book for book in engine.BOOKS if book.id == "desk-runner"), snap(), path)
    assert runner["reason"] == "trail"


def test_stats():
    same = engine.bootstrap_ci([1, 1, 1, 1], draws=50, seed=1)
    assert same["low"] == same["high"] == 1
    mixed = [1, -1] * 20
    ci = engine.bootstrap_ci(mixed, draws=200, seed=2)
    assert engine.verdict(40, ci) == "not distinguishable from luck"
    assert engine.verdict(10, ci) == "too few trades to tell"
    assert engine.verdict(40, {"low": 0.1, "high": 0.2}) == "beats zero"
    assert engine.sample_label(10) == "early"
    assert engine.sample_label(120) == "meaningful"
    assert engine.sample_label(300) == "trustworthy"
    pct = engine.random_percentile(50, [-1] * 20, 5, draws=100, seed=3)
    assert pct == 100


def test_desk_losses():
    assert engine.classify_desk_trade(
        {"event": "BUY"}, [{"event": "SELL", "x": 0.2, "note": "stop-loss"}],
        {"event": "CLOSED", "x": 0.2, "sol_pnl": -0.05, "note": "position total"},
    ) == "rug"
    assert engine.classify_desk_trade(
        {"event": "BUY"}, [{"event": "SELL", "x": 2.2, "note": "ladder 2.0X"}],
        {"event": "CLOSED", "x": 0.8, "sol_pnl": -0.01, "note": "position total"},
    ) == "gave back gains"
    assert engine.classify_desk_trade(
        {"event": "BUY"}, [{"event": "SELL", "x": 0.9, "note": "agent cut"}],
        {"event": "CLOSED", "x": 0.9, "sol_pnl": -0.02, "note": "position total"},
    ) == "sold too early"
    assert engine.classify_desk_trade(
        {"event": "BUY"}, [{"event": "SELL", "x": 0.8, "note": "time-stop"}],
        {"event": "CLOSED", "x": 0.8, "sol_pnl": -0.02, "note": "position total"},
    ) == "slow bleed"
    assert engine.classify_desk_trade(
        {"event": "BUY"}, [],
        {"event": "CLOSED", "x": 2, "sol_pnl": 0.1, "note": "position total"},
    ) is None


def test_record_scan():
    path = os.path.join(tempfile.mkdtemp(), "lab.sqlite")
    store = lab.Store(path)
    payload = {
        "scanned_at": 1000,
        "candidates": [{
            "mint": "Mint111",
            "symbol": "AAA",
            "score": 77,
            "decision": "skip",
            "note": "thin liquidity",
            "sources": ["gmgn", "fomo"],
            "mcap": 4000,
            "liq": 1000,
            "change_5m": 8,
            "price_sol": 0.001,
            "age_min": 12,
            "rug_label": "clean",
        }],
    }
    assert lab.record_scan(store, payload, now=1000) == 1
    assert lab.record_scan(store, payload, now=1060) == 0
    counts = store.counts()
    assert counts["hits"] == 1
    assert counts["episodes"] == 1
    episodes = store.episodes_for_report()
    assert episodes[0]["decision"] == "skip"
    assert episodes[0]["sources"] == ["gmgn", "fomo"]
    report = lab.build_report(store)
    assert report["sample"] == "early"
    assert len(report["books"]) == 10
    assert [row["size_usd"] for row in report["tickets"]] == [5.5, 8.0, 12.0]
    assert [row["id"] for row in report["baselines"]] == ["hold-sol", "buy-every-name"]
    assert report["readiness"]["ready"] is False


if __name__ == "__main__":
    test_books_and_fills()
    test_stats()
    test_desk_losses()
    test_record_scan()
    print("selftest ok")
