"""Wrapper LLM pluggable.

Dipakai Agent 1/2/4 untuk merangkai *narasi* (bukan menghitung angka) dan
Agent 6 untuk membaca screenshot portofolio (vision).

Provider yang didukung:
  - anthropic  : SDK resmi Anthropic (format Messages).
  - openrouter : endpoint OpenAI-compatible OpenRouter (bisa akses model
                 Claude/Gemini/dll., mis. model "anthropic/claude-3.5-haiku").
  - none       : lewati LLM; agent memakai template fallback.

Jika API key kosong atau paket belum terpasang, fungsi mengembalikan None
sehingga sistem tetap berjalan tanpa LLM.
"""
from __future__ import annotations

import base64

from src.config import settings
from src.core.logging_conf import get_logger

log = get_logger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _provider() -> str:
    return settings.llm_provider.lower()


# --------------------------------------------------------------------------
# Anthropic (format Messages)
# --------------------------------------------------------------------------
def _anthropic_client():
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY kosong — langkah LLM dilewati.")
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("paket 'anthropic' belum terpasang — langkah LLM dilewati.")
        return None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _anthropic_complete(prompt: str, system: str, max_tokens: int) -> str | None:
    client = _anthropic_client()
    if client is None:
        return None
    msg = client.messages.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _anthropic_vision(b64: str, prompt: str, media_type: str) -> str | None:
    client = _anthropic_client()
    if client is None:
        return None
    msg = client.messages.create(
        model=settings.llm_vision_model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


# --------------------------------------------------------------------------
# OpenRouter (format OpenAI chat.completions)
# --------------------------------------------------------------------------
def _openrouter_client():
    if not settings.openrouter_api_key:
        log.warning("OPENROUTER_API_KEY kosong — langkah LLM dilewati.")
        return None
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("paket 'openai' belum terpasang — jalankan: pip install openai")
        return None
    # Header opsional untuk peringkat OpenRouter (boleh dikosongkan).
    headers = {"X-Title": "trading-agent-tio"}
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=settings.openrouter_api_key,
        default_headers=headers,
    )


def _openrouter_complete(prompt: str, system: str, max_tokens: int) -> str | None:
    client = _openrouter_client()
    if client is None:
        return None
    resp = client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content


def _openrouter_vision(b64: str, prompt: str, media_type: str) -> str | None:
    client = _openrouter_client()
    if client is None:
        return None
    data_url = f"data:{media_type};base64,{b64}"
    resp = client.chat.completions.create(
        model=settings.llm_vision_model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    )
    return resp.choices[0].message.content


# --------------------------------------------------------------------------
# API publik
# --------------------------------------------------------------------------
def complete(prompt: str, system: str = "", max_tokens: int = 1024) -> str | None:
    """Minta teks dari LLM. Kembalikan None bila LLM tidak tersedia."""
    system = system or "Anda analis pasar saham Indonesia yang ringkas dan objektif."
    try:
        if _provider() == "anthropic":
            return _anthropic_complete(prompt, system, max_tokens)
        if _provider() == "openrouter":
            return _openrouter_complete(prompt, system, max_tokens)
        return None  # provider 'none' atau tidak dikenal
    except Exception as exc:  # noqa: BLE001 — jangan sampai LLM menjatuhkan agent
        log.error("Panggilan LLM gagal: %s", exc)
        return None


def read_image(image_bytes: bytes, prompt: str, media_type: str = "image/png") -> str | None:
    """Vision: ekstrak informasi dari gambar. Kembalikan None bila tak tersedia."""
    try:
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        if _provider() == "anthropic":
            return _anthropic_vision(b64, prompt, media_type)
        if _provider() == "openrouter":
            return _openrouter_vision(b64, prompt, media_type)
        return None
    except Exception as exc:  # noqa: BLE001
        log.error("Panggilan Vision LLM gagal: %s", exc)
        return None
