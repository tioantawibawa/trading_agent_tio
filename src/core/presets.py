"""Preset daftar saham (mis. indeks LQ45).

CATATAN: Konstituen LQ45 direvisi BEI tiap 6 bulan (Februari & Agustus).
Daftar di bawah adalah SNAPSHOT dan bisa berbeda dari periode berjalan.
Perbarui manual bila BEI merilis komposisi baru, atau muat dari file eksternal.
"""
from __future__ import annotations

# Snapshot LQ45 (~periode 2025). 45 emiten paling likuid di BEI.
LQ45: list[str] = [
    "ACES", "ADMR", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ARTO", "ASII", "BBCA",
    "BBNI", "BBRI", "BBTN", "BMRI", "BRIS", "BRPT", "CPIN", "CTRA", "ESSA", "EXCL",
    "GOTO", "ICBP", "INCO", "INDF", "INKP", "INTP", "ISAT", "ITMG", "JSMR", "KLBF",
    "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SIDO", "SMGR", "SRTG",
    "TLKM", "TOWR", "UNTR", "UNVR", "MAPA",
]

PRESETS: dict[str, list[str]] = {
    "lq45": LQ45,
}


def get_preset(name: str) -> list[str]:
    return PRESETS.get(name.lower(), [])
