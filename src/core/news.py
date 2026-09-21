"""Pengambilan data tak terstruktur: berita finansial via RSS.

Dipakai Agent 1. Sumber RSS bersifat konfigurable; sesuaikan/ tambah sesuai
portal favorit Anda. Untuk sumber tanpa RSS (mis. keterbukaan informasi IDX,
forum), tambahkan scraper terpisah dengan menghormati robots.txt & ToS.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.logging_conf import get_logger

log = get_logger(__name__)

# Feed RSS portal finansial Indonesia (sesuaikan bila berubah).
DEFAULT_FEEDS: list[str] = [
    "https://www.cnbcindonesia.com/market/rss",
    "https://investasi.kontan.co.id/rss",
    "https://www.bisnis.com/rss",
]


def fetch_news(feeds: list[str] | None = None, limit_per_feed: int = 20) -> list[dict[str, Any]]:
    """Ambil headline berita terbaru dari daftar feed RSS.

    Mengembalikan list dict: {title, link, published, source}.
    Gagal pada satu feed tidak menggagalkan keseluruhan.
    """
    try:
        import feedparser
    except ImportError:
        log.warning("paket 'feedparser' belum terpasang — melewati pengambilan berita.")
        return []

    items: list[dict[str, Any]] = []
    for url in feeds or DEFAULT_FEEDS:
        try:
            parsed = feedparser.parse(url)
            source = parsed.feed.get("title", url) if hasattr(parsed, "feed") else url
            for entry in parsed.entries[:limit_per_feed]:
                items.append(
                    {
                        "title": entry.get("title", "").strip(),
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": source,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Gagal ambil feed %s: %s", url, exc)
    log.info("Terkumpul %d headline dari %d feed.", len(items), len(feeds or DEFAULT_FEEDS))
    return items


def mentioned_tickers(news_items: list[dict[str, Any]], universe: list[str]) -> dict[str, int]:
    """Hitung berapa kali tiap ticker (dari universe) disebut di judul berita.

    Heuristik sederhana berbasis pencocokan kode; untuk sentimen sesungguhnya,
    serahkan judul-judul ini ke LLM (lihat Agent 1)."""
    counts: dict[str, int] = {}
    for item in news_items:
        title_up = item.get("title", "").upper()
        for tk in universe:
            if tk.upper() in title_up:
                counts[tk.upper()] = counts.get(tk.upper(), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def now_iso() -> str:
    return datetime.utcnow().isoformat()
