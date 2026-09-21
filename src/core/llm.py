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
_MODEL_CACHE: dict[str, str] = {}        # kind -> model yang terbukti berhasil
_MODEL_CACHE_LIST: dict[str, list[str]] = {}  # 'list_<kind>' -> daftar kandidat
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


_MAX_CANDIDATES = 6  # berapa banyak model gratis dicoba sebelum menyerah


def _free_model_list(kind: str) -> list[str]:
    """Daftar model GRATIS terurut (terbaik dulu) untuk dicoba bergiliran.

    Model :free memakai kolam bersama yang sering rate-limited (429); dengan
    daftar ini, bila satu model gagal, pemanggil mencoba model berikutnya.
    """
    cache_key = f"list_{kind}"
    if cache_key in _MODEL_CACHE_LIST:
        return _MODEL_CACHE_LIST[cache_key]
    try:
        models = _fetch_openrouter_models()
    except Exception as exc:  # noqa: BLE001
        log.warning("Gagal ambil daftar model OpenRouter: %s", exc)
        models = []

    free = [m for m in models if _is_free(m)]
    if kind == "vision":
        free = [m for m in free if _supports_image(m)]

    pref = ("gemini", "llama", "qwen", "deepseek", "mistral", "glm")
    def _score(m: dict):
        idl = m.get("id", "").lower()
        fam = next((len(pref) - i for i, k in enumerate(pref) if k in idl), 0)
        # Untuk vision, utamakan model yang jelas bertipe visual.
        vbonus = 0
        if kind == "vision" and any(k in idl for k in ("gemini", "-vl", "vision", "pixtral")):
            vbonus = 10
        return (vbonus + fam, m.get("context_length") or 0)

    free.sort(key=_score, reverse=True)
    ids = [m["id"] for m in free][:_MAX_CANDIDATES]
    for cand in (_FALLBACK_VISION if kind == "vision" else _FALLBACK_TEXT):
        if cand not in ids:
            ids.append(cand)
    _MODEL_CACHE_LIST[cache_key] = ids
    if ids:
        log.info("LLM kandidat model gratis (%s): %s", kind, ", ".join(ids[:4]) + " ...")
    return ids


def _candidate_models(kind: str) -> list[str]:
    """Model yang akan dicoba: nilai .env eksplisit, atau daftar gratis (auto)."""
    configured = settings.llm_vision_model if kind == "vision" else settings.llm_model
    if configured and configured.strip().lower() != "auto":
        return [configured]
    ids = list(_free_model_list(kind))
    # Dahulukan model yang terbukti berhasil pada panggilan sebelumnya.
    winner = _MODEL_CACHE.get(kind)
    if winner and winner in ids:
        ids.remove(winner)
        ids.insert(0, winner)
    return ids


def _resolve_model(kind: str) -> str | None:
    """Model pilihan pertama (untuk ditampilkan perintah `llm-model`)."""
    cands = _candidate_models(kind)
    return cands[0] if cands else None


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
    # max_retries=0: retry 429 ditangani sendiri dgn pindah model, bukan menunggu.
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=settings.openrouter_api_key,
        default_headers=headers,
        max_retries=0,
    )


def _openrouter_call(kind: str, messages: list, max_tokens: int) -> str | None:
    """Coba model kandidat satu per satu; lewati yang 429/404/error."""
    client = _openrouter_client()
    if client is None:
        return None
    candidates = _candidate_models(kind)
    if not candidates:
        log.warning("Tidak ada model %s tersedia.", kind)
        return None
    for model in candidates:
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=max_tokens, messages=messages,
            )
            content = resp.choices[0].message.content
            if content:
                _MODEL_CACHE[kind] = model  # ingat yang berhasil untuk berikutnya
                return content
        except Exception as exc:  # noqa: BLE001
            log.warning("Model %s gagal (%s) — coba model lain.", model, str(exc)[:100])
            continue
    log.error("Semua model %s gagal (kemungkinan rate-limit kolam gratis).", kind)
    return None


def _openrouter_complete(prompt: str, system: str, max_tokens: int) -> str | None:
    return _openrouter_call("text", [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ], max_tokens)


def _openrouter_vision(b64: str, prompt: str, media_type: str) -> str | None:
    data_url = f"data:{media_type};base64,{b64}"
    return _openrouter_call("vision", [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }], 1500)


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
