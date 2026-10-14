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
    assert len(engine.BOOKS) == 20
    assert len({book.id for book in engine.BOOKS}) == 20
    assert engine.REFERENCE_ID in {book.id for book in engine.BOOKS}
    assert engine.round_trip_cost_usd(5.5, 10000) == 0.85
    filters = engine.book_by_id("filters-ladder")
    assert engine.would_enter(filters, snap(score=10, sources=["pump.fun"], change_5m=0))
    assert not engine.would_enter(filters, snap(note="rugcheck: rugged"))
    assert engine.would_enter(filters, snap(note="rugcheck 12"))
    harsh = engine.round_trip(1, 1, 5, 100)
    calm = engine.round_trip(1, 1, 5, 100000)
    assert harsh < calm < 0
    assert engine.vanished_pnl() < -4
    assert not engine.would_enter(engine.BOOKS[0], snap(note="rugcheck: rugged"))
    strict = next(book for book in engine.BOOKS if book.id == "strict-ladder")
    desk = next(book for book in engine.BOOKS if book.id == "desk-ladder")
    assert not engine.would_enter(strict, snap(score=65))
    assert engine.would_enter(strict, snap(score=75))
    assert not engine.would_enter(strict, snap(sources=["gmgn", "dexscreener"]))
    assert engine.would_enter(desk, snap())
    assert engine.simulate(desk, snap(), []) is None
    late = path_from([(m, 1.0) for m in range(10, 60)])
    assert engine.simulate(desk, snap(), late) is None
    path = rise_and_fade()
    ladder = engine.simulate(desk, snap(), path)
    cut = engine.simulate(next(book for book in engine.BOOKS if book.id == "desk-cut"), snap(), path)
    assert "ladder" in ladder["reason"] or ladder["pnl"] != cut["pnl"]
    assert cut["reason"] == "early-cut"
    assert ladder["pnl"] != cut["pnl"]
    runner = engine.simulate(next(book for book in engine.BOOKS if book.id == "desk-runner"), snap(), path)
    assert runner["reason"] == "trail"


def test_costs_and_breakdown():
    assert engine.slippage(5.5, 0) == 0.03
    assert abs(engine.slippage(5.5, 10000) - (0.03 + 2 * 5.5 / 10000)) < 1e-12
    assert engine.slippage(5.5, 1) == 0.80
    parts = engine.piece_parts(1.0, 2.0, 5.0, 1.0, 20000)
    assert abs(sum(parts.values()) - engine.piece(1.0, 2.0, 5.0, 20000)) < 1e-12
    assert parts["move"] == 5.0 and parts["slippage"] < 0 and parts["fee"] < 0 and parts["flat"] == -0.20
    path = rise_and_fade()
    for book in engine.BOOKS:
        trade = engine.simulate(book, snap(), path)
        assert abs(sum(trade["parts"].values()) - trade["pnl"]) < 1e-9
        assert trade["peak"] >= 1.0
    crash = path_from([(0, 1.0), (1, 1.0), (2, 0.6), (3, 0.3)])
    stop = engine.simulate(next(b for b in engine.BOOKS if b.id == "desk-cut"), snap(), crash)
    assert stop["reason"] == "stop" and stop["parts"]["stop_gap"] < 0
    assert abs(stop["parts"]["move"] + stop["parts"]["stop_gap"] - 5.0 * (0.3 - 1)) < 1e-9
    assert engine.label_2x(path, 0.0) is True
    assert engine.label_2x(crash, 0.0) is False
    dip = path_from([(0, 1.0), (1, 1.0), (2, 0.85), (3, 1.2)] + [(m, 1.2) for m in range(4, 241)])
    assert engine.entry_point(dip, 0.0, "pullback")[1] == 0.85
    assert engine.entry_point(dip, 0.0, "hold")[1] == 1.2
    assert engine.entry_point(crash, 0.0, "hold") is None
    assert engine.auc([1, 2, 3, 4], [False, False, True, True]) == 1.0
    assert engine.auc([1, 1, 1, 1], [False, True, False, True]) == 0.5


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
            "features": {"buy_sell_5m": 1.4, "creator": "Creator1"},
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
    assert len(report["books"]) == 20
    assert [row["size_usd"] for row in report["tickets"]] == [5.5, 8.0, 12.0] * 3
    assert report["real_desk"]["id"] == engine.REAL_DESK_ID
    assert report["readiness"]["book"] == engine.REAL_DESK_ID
    assert report["verdict"]["verdict"] == "Not yet"
    assert report["quotes"]["calibrated"] is False
    assert [row["id"] for row in report["baselines"]] == ["hold-sol", "buy-every-name"]
    assert report["readiness"]["ready"] is False
    assert episodes[0]["features"]["buy_sell_5m"] == 1.4
    assert episodes[0]["features"]["creator_launches"] == 0
    assert [d["problem"] for d in report["diagnosis"]] == [
        "signal is weak", "costs eat a real edge", "exits give gains back",
    ]
    assert report["model"]["status"].startswith("collecting")
    assert report["stop_rule"]["verdict"].startswith("keep collecting")
    assert report["regime"]["pause"] is False
    text = lab.format_report(report)
    assert "Diagnosis" in text and "Weekly verdict" in text


def _confirm_row(book_id, n, mean, low, high, gross, costs):
    return {"id": book_id, "n": n, "mean": mean, "ci": {"low": low, "high": high},
            "parts": {"before_costs": gross, "costs": costs}, "paired": None}


def test_verdict():
    after = lab.research_windows()["confirm_until"] + engine.TRACK_S + 1
    cal = {"calibrated": True, "shift_usd": 0.05, "why": ""}
    every = {"n": 200, "mean": -0.40}
    res = {"windows": {"freeze_at": "f", "confirm_until": "c"}, "frozen": {"picks": ["loose-ladder"]},
           "confirm_every": every}
    res["confirm"] = [_confirm_row("loose-ladder", 80, 0.50, 0.20, 0.80, 1.40, -0.90)]
    assert lab.weekly_verdict(res, cal, after)["verdict"] == "Edge found"
    uncal = {"calibrated": False, "shift_usd": 0.0, "why": "needs quotes"}
    assert lab.weekly_verdict(res, uncal, after)["verdict"] == "Not yet"
    res["confirm"] = [_confirm_row("loose-ladder", 30, 0.50, -0.20, 1.20, 1.40, -0.90)]
    assert lab.weekly_verdict(res, cal, after)["verdict"] == "Not yet"
    res["confirm"] = [_confirm_row("loose-ladder", 80, -0.30, -0.60, -0.05, 0.60, -0.90)]
    assert lab.weekly_verdict(res, cal, after)["verdict"] == "Costs only"
    res["confirm"] = [_confirm_row("loose-ladder", 80, -1.30, -1.60, -1.05, -0.40, -0.90)]
    assert lab.weekly_verdict(res, cal, after)["verdict"] == "No edge"
    res["frozen"] = None
    assert lab.weekly_verdict(res, cal, after)["verdict"] == "Not yet"


if __name__ == "__main__":
    test_books_and_fills()
    test_costs_and_breakdown()
    test_stats()
    test_desk_losses()
    test_record_scan()
    test_verdict()
    print("selftest ok")
