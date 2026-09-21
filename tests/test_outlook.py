"""Uji logika prospek 7 hari (format & rekomendasi) — tanpa jaringan."""
from src.core import outlook


def test_trend_detection():
    up = list(range(100, 140))  # menaik
    assert outlook._trend([float(x) for x in up]) == "naik"
    down = list(range(140, 100, -1))
    assert outlook._trend([float(x) for x in down]) == "turun"


def test_recommendation_take_profit():
    o = {"current": 5200, "target": 5150, "stop": 4700, "trend": "naik",
         "avg_price": 4500, "floating_pct": 15.5, "support": 4700}
    assert "Take Profit" in outlook._recommendation(o)


def test_recommendation_cut_loss():
    o = {"current": 4300, "target": 5150, "stop": 4350, "trend": "turun",
         "avg_price": 4500, "floating_pct": -4.4, "support": 4350}
    assert "Cut Loss" in outlook._recommendation(o)


def test_recommendation_accumulate_when_not_holding():
    o = {"current": 4710, "target": 5150, "stop": 4600, "trend": "naik",
         "support": 4700}
    assert "akumulasi" in outlook._recommendation(o).lower()


def test_format_outlook_html_contains_key_fields():
    o = {
        "ticker": "ASII", "current": 4880, "trend": "naik", "atr": 90,
        "support": 4700, "resistance": 5150, "proj_low": 4650, "proj_high": 5100,
        "target": 5150, "stop": 4700, "upside_pct": 5.5, "horizon_days": 7,
        "avg_price": 4500, "floating_pct": 8.4, "action": "Hold",
    }
    html = outlook.format_outlook_html(o)
    assert "ASII" in html and "Target" in html and "7 hari" in html
