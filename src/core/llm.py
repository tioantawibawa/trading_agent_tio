"""Wrapper LLM pluggable.

Dipakai Agent 1/2/4 untuk merangkai *narasi* (bukan menghitung angka) dan
Agent 6 untuk membaca screenshot portofolio (vision).

Provider default: Anthropic. Jika `LLM_PROVIDER=none` atau API key kosong,
fungsi mengembalikan `None` sehingga agent memakai template fallback —
sistem tetap berjalan tanpa LLM.
"""
from __future__ import annotations

import base64
from typing import Any

from src.config import settings
from src.core.logging_conf import get_logger

log = get_logger(__name__)


def _client() -> Any | None:
    if settings.llm_provider.lower() != "anthropic":
        return None
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY kosong — langkah LLM dilewati.")
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("paket 'anthropic' belum terpasang — langkah LLM dilewati.")
        return None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def complete(prompt: str, system: str = "", max_tokens: int = 1024) -> str | None:
    """Minta teks dari LLM. Kembalikan None bila LLM tidak tersedia."""
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system or "Anda analis pasar saham Indonesia yang ringkas dan objektif.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception as exc:  # noqa: BLE001 — jangan sampai LLM menjatuhkan agent
        log.error("Panggilan LLM gagal: %s", exc)
        return None


def read_image(image_bytes: bytes, prompt: str, media_type: str = "image/png") -> str | None:
    """Vision: ekstrak informasi dari gambar. Kembalikan None bila tak tersedia."""
    client = _client()
    if client is None:
        return None
    try:
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        msg = client.messages.create(
            model=settings.llm_vision_model,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception as exc:  # noqa: BLE001
        log.error("Panggilan Vision LLM gagal: %s", exc)
        return None
