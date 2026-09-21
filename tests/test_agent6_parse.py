"""Uji ketangguhan parser JSON Agent 6 terhadap output vision yang 'kotor'."""
from src.agents.agent6_portfolio import _parse_json


def test_parse_clean_json():
    txt = '{"cash_balance": 15511232, "positions": []}'
    d = _parse_json(txt)
    assert d and d["cash_balance"] == 15511232


def test_parse_with_markdown_fence_and_thousands():
    txt = (
        "```json\n"
        '{"cash_balance": 15,511,232, "positions": ['
        '{"ticker": "BBRI", "lots": 493, "avg_price": null, '
        '"last_price": null, "floating_pl_rp": -47,847,530, '
        '"floating_pl_pct": -22.7}]}\n'
        "```"
    )
    d = _parse_json(txt)
    assert d is not None
    assert d["cash_balance"] == 15511232
    pos = d["positions"][0]
    assert pos["ticker"] == "BBRI"
    assert pos["lots"] == 493
    assert pos["floating_pl_rp"] == -47847530
    assert pos["floating_pl_pct"] == -22.7


def test_parse_with_rp_prefix_and_trailing_comma():
    txt = '{"cash_balance": Rp1,000,000, "positions": [],}'
    d = _parse_json(txt)
    assert d and d["cash_balance"] == 1000000


def test_parse_with_leading_prose():
    txt = 'Berikut hasilnya:\n{"cash_balance": 500000, "positions": []}'
    d = _parse_json(txt)
    assert d and d["cash_balance"] == 500000


def test_parse_garbage_returns_none():
    assert _parse_json("tidak ada json di sini") is None
    assert _parse_json("") is None
