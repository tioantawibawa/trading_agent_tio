"""Indikator teknikal deterministik untuk Agent 3.

SEMUA angka (ATR, support/resistance, pivot) dihitung di sini dengan formula,
bukan LLM — agar harga entry/SL/TP presisi dan bebas halusinasi.
"""
from __future__ import annotations

from typing import Any


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def sma(values: list[float], period: int) -> float | None:
    """Simple Moving Average dari `period` nilai terakhir."""
    return _sma(values, period)


def trend_label(closes: list[float]) -> str:
    """Klasifikasi tren dari SMA5 vs SMA20: 'naik' | 'turun' | 'sideways'."""
    s5, s20 = _sma(closes, 5), _sma(closes, 20)
    if s5 is None or s20 is None:
        return "belum jelas"
    last = closes[-1]
    if s5 > s20 * 1.005 and last >= s20:
        return "naik"
    if s5 < s20 * 0.995 and last <= s20:
        return "turun"
    return "sideways"


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Relative Strength Index (0-100). None bila data kurang."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = sum(d for d in recent if d > 0) / period
    losses = sum(-d for d in recent if d < 0) / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """True Range per bar (butuh close bar sebelumnya)."""
    trs: list[float] = []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Average True Range — ukuran volatilitas untuk toleransi noise & sizing."""
    trs = true_ranges(highs, lows, closes)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def pivot_points(high: float, low: float, close: float) -> dict[str, float]:
    """Pivot klasik intraday (P, S1/S2, R1/R2)."""
    p = (high + low + close) / 3
    return {
        "pivot": p,
        "r1": 2 * p - low,
        "r2": p + (high - low),
        "s1": 2 * p - high,
        "s2": p - (high - low),
    }


def recent_support_resistance(
    highs: list[float], lows: list[float], lookback: int = 20
) -> tuple[float, float]:
    """Support = low terendah; Resistance = high tertinggi dalam lookback."""
    hs = highs[-lookback:] if len(highs) >= lookback else highs
    ls = lows[-lookback:] if len(lows) >= lookback else lows
    if not hs or not ls:
        return (0.0, 0.0)
    return (min(ls), max(hs))


def volume_spike(volumes: list[float], multiplier: float, lookback: int = 20) -> dict[str, Any]:
    """Deteksi lonjakan volume: volume terakhir vs rata-rata `lookback` hari
    sebelumnya. Kembalikan rasio & flag."""
    if len(volumes) < lookback + 1:
        return {"is_spike": False, "ratio": None, "avg": None, "last": volumes[-1] if volumes else None}
    last = volumes[-1]
    avg = sum(volumes[-(lookback + 1):-1]) / lookback
    ratio = (last / avg) if avg else None
    return {
        "is_spike": bool(ratio and ratio >= multiplier),
        "ratio": ratio,
        "avg": avg,
        "last": last,
    }
