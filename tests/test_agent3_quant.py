"""Uji Agent 3: konsistensi plan + filter kualitas (tren/RSI/risiko)."""
from src.agents.agent3_quant import build_plan
from src.config import settings


def _uptrend_series(n=40, start=1000, step=8, noise_high=12, noise_low=12):
    closes = [start + i * step for i in range(n)]
    highs = [c + noise_high for c in closes]
    lows = [c - noise_low for c in closes]
    volumes = [1_000_000] * n
    return closes, highs, lows, volumes


def test_breakout_plan_consistency():
    closes, highs, lows, volumes = _uptrend_series()
    resistance = max(highs)
    daily = {
        "closes": closes, "highs": highs, "lows": lows, "volumes": volumes,
        "prev_close": closes[-1], "prev_high": highs[-1], "prev_low": lows[-1],
        # Harga menembus resistance -> Buy on Breakout.
        "intraday_last": resistance + 5,
    }
    plan = build_plan("TEST", daily)
    assert plan is not None
    assert plan["recommendation"] == "Buy on Breakout"
    assert plan["stop_loss"] < plan["entry_low"] <= plan["entry_high"] <= plan["take_profit"]
    assert plan["rrr"] is not None and plan["rrr"] >= settings.min_rrr - 0.01
    assert plan["risk_pct"] <= settings.max_stoploss_pct + 0.01
    assert plan["take_profit"] <= plan["ara"]
    assert plan["trend"] in ("naik", "sideways")


def test_downtrend_is_skipped():
    # Tren menurun jelas -> harus dilewati (hindari pisau jatuh).
    n = 40
    closes = [2000 - i * 8 for i in range(n)]
    highs = [c + 12 for c in closes]
    lows = [c - 12 for c in closes]
    daily = {
        "closes": closes, "highs": highs, "lows": lows,
        "prev_close": closes[-1], "prev_high": highs[-1], "prev_low": lows[-1],
        "intraday_last": closes[-1],
    }
    assert build_plan("DOWN", daily) is None


def test_insufficient_data():
    assert build_plan("X", {"closes": [1, 2], "highs": [1, 2], "lows": [1, 2]}) is None


def test_no_chasing_far_above_support():
    # Uptrend, harga di tengah range (jauh di atas support, belum breakout) ->
    # Buy on Weakness tapi harga mengejar -> dilewati.
    closes, highs, lows, volumes = _uptrend_series(step=20)  # range sangat lebar
    daily = {
        "closes": closes, "highs": highs, "lows": lows, "volumes": volumes,
        "prev_close": closes[-1], "prev_high": highs[-1], "prev_low": lows[-1],
        "intraday_last": (min(lows) + max(highs)) / 2,  # tengah, jauh dari support
    }
    # Tidak breakout & mengejar dari support -> None.
    assert build_plan("MID", daily) is None
