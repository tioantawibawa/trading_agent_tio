"""Uji Agent 3: plan harus konsisten (SL < entry < TP, RRR terpenuhi, batas AR)."""
from src.agents.agent3_quant import build_plan
from src.config import settings


def _synthetic_daily():
    # Data naik bertahap + volatilitas kecil, cukup untuk ATR(14).
    n = 40
    closes = [1000 + i * 5 for i in range(n)]
    highs = [c + 15 for c in closes]
    lows = [c - 15 for c in closes]
    volumes = [1_000_000] * n
    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "prev_close": closes[-2],
        "prev_high": highs[-1],
        "prev_low": lows[-1],
        "intraday_last": closes[-1],
    }


def test_build_plan_consistency():
    plan = build_plan("TEST", _synthetic_daily())
    assert plan is not None
    assert plan["stop_loss"] < plan["entry_low"] <= plan["entry_high"] <= plan["take_profit"]
    # RRR harus terhitung dan >= minimal (build_plan mengejar min_rrr).
    assert plan["rrr"] is not None
    assert plan["rrr"] >= settings.min_rrr - 0.01
    # TP tidak melebihi ARA, SL tidak di bawah ARB.
    assert plan["take_profit"] <= plan["ara"]
    assert plan["stop_loss"] >= plan["arb"]


def test_build_plan_insufficient_data():
    assert build_plan("TEST", {"closes": [1, 2], "highs": [1, 2], "lows": [1, 2]}) is None
