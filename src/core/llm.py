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
_MODEL_CACHE: dict[str, str] = {}
# Kandidat cadangan (umumnya ada sebagai gratis) bila auto-deteksi gagal.
_FALLBACK_TEXT = ["deepseek/deepseek-chat-v3.1:free", "google/gemini-2.0-flash-exp:free"]
_FALLBACK_VISION = ["google/gemini-2.0-flash-exp:free"]


def _fetch_openrouter_models() -> list[dict]:
    import requests

    r = requests.get(OPENROUTER_BASE_URL + "/models", timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def _is_free(m: dict) -> bool:
    p = m.get("pricing") or {}
    try:
        return float(p.get("prompt", 1)) == 0 and float(p.get("completion", 1)) == 0
    except (TypeError, ValueError):
        return False


def _supports_image(m: dict) -> bool:
    arch = m.get("architecture") or {}
    mods = arch.get("input_modalities") or arch.get("modality") or ""
    return "image" in (mods if isinstance(mods, list) else [mods]) or "image" in str(mods)


def _pick_free_model(kind: str) -> str | None:
    """Pilih otomatis model GRATIS terbaik dari OpenRouter.

    kind: 'text' | 'vision'. Hasil di-cache per proses. Kembalikan None bila
    tak ada model gratis yang cocok (agent lalu memakai template).
    """
    if kind in _MODEL_CACHE:
        return _MODEL_CACHE[kind]
    try:
        models = _fetch_openrouter_models()
    except Exception as exc:  # noqa: BLE001
        log.warning("Gagal ambil daftar model OpenRouter: %s", exc)
        models = []

    free = [m for m in models if _is_free(m)]
    if kind == "vision":
        free = [m for m in free if _supports_image(m)]

    # Urutkan: prefer keluarga populer & stabil, lalu context length terbesar.
    pref = ("gemini", "llama", "qwen", "deepseek", "mistral", "glm")
    def _score(m: dict):
        idl = m.get("id", "").lower()
        fam = next((len(pref) - i for i, k in enumerate(pref) if k in idl), 0)
        return (fam, m.get("context_length") or 0)

    free.sort(key=_score, reverse=True)
    chosen = None
    if free:
        chosen = free[0]["id"]
    else:
        # Coba kandidat cadangan yang memang ada di daftar (bila terambil).
        ids = {m.get("id") for m in models}
        for cand in (_FALLBACK_VISION if kind == "vision" else _FALLBACK_TEXT):
            if not models or cand in ids:
                chosen = cand
                break

    if chosen:
        _MODEL_CACHE[kind] = chosen
        log.info("LLM auto-pilih model gratis (%s): %s", kind, chosen)
    else:
        log.warning("Tidak menemukan model gratis untuk %s.", kind)
    return chosen


def _resolve_model(kind: str) -> str | None:
    """Kembalikan nama model: pakai nilai .env, atau auto-pilih bila 'auto'/kosong."""
    configured = settings.llm_vision_model if kind == "vision" else settings.llm_model
    if configured and configured.strip().lower() != "auto":
        return configured
    return _pick_free_model(kind)


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
    model = _resolve_model("text")
    if not model:
        return None
    resp = client.chat.completions.create(
        model=model,
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
    model = _resolve_model("vision")
    if not model:
        return None
    data_url = f"data:{media_type};base64,{b64}"
    resp = client.chat.completions.create(
        model=model,
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
