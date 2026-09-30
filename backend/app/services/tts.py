"""Sintesi vocale (voci naturali) con OpenAI o Gemini, con cache su disco per frase+voce+stile."""
from __future__ import annotations

import asyncio
import hashlib
import struct
from pathlib import Path

from ..config import get_settings

settings = get_settings()

MAX_CHARS = 2000
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
GEMINI_VOICES = ["Kore", "Puck", "Zephyr", "Charon", "Fenrir", "Leda", "Aoede", "Orus", "Callirrhoe", "Autonoe"]
DEFAULT_STYLE = ("Parla in italiano con voce calda, chiara e naturale, ritmo tranquillo, tono gentile e allegro, "
                 "come chi legge a un bambino.")

_locks: dict[str, asyncio.Lock] = {}


def provider() -> str:
    """Provider effettivo: openai | gemini | '' (disabilitato)."""
    pref = (getattr(settings, "tts_provider", "auto") or "auto").lower()
    if pref == "none":
        return ""
    if pref == "openai":
        return "openai" if settings.openai_api_key else ""
    if pref == "gemini":
        return "gemini" if settings.gemini_api_key else ""
    return "openai" if settings.openai_api_key else ("gemini" if settings.gemini_api_key else "")


def enabled() -> bool:
    return bool(provider())


def _cache_dir() -> Path:
    p = settings.data_dir / "tts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE" + b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, rate * channels * width, channels * width, width * 8) + b"data" + struct.pack("<I", len(pcm))
    return header + pcm


async def synthesize(text: str, voice: str | None = None, style: str | None = None) -> tuple[bytes, str]:
    """Restituisce (audio, mime). Solleva RuntimeError con messaggio leggibile se non disponibile."""
    text = " ".join(text.split())[:MAX_CHARS]
    if not text:
        raise RuntimeError("Testo vuoto")
    prov = provider()
    if not prov:
        raise RuntimeError("Sintesi vocale non configurata: serve una chiave OpenAI o Gemini")
    if prov == "openai":
        model = settings.tts_model_openai or "gpt-4o-mini-tts"
        voice = (voice or settings.tts_voice_openai or "nova").lower()
        if voice not in OPENAI_VOICES:
            voice = settings.tts_voice_openai if settings.tts_voice_openai in OPENAI_VOICES else "nova"
        mime, ext = "audio/mpeg", "mp3"
    else:
        model = settings.tts_model_gemini or "gemini-2.5-flash-preview-tts"
        voice = voice or settings.tts_voice_gemini or "Kore"
        if voice not in GEMINI_VOICES:
            voice = settings.tts_voice_gemini if settings.tts_voice_gemini in GEMINI_VOICES else "Kore"
        mime, ext = "audio/wav", "wav"
    style = (style or settings.tts_style or DEFAULT_STYLE).strip()[:500]

    key = hashlib.sha256(f"{prov}|{model}|{voice}|{style}|{text}".encode()).hexdigest()
    path = _cache_dir() / f"{key}.{ext}"
    if path.exists():
        return path.read_bytes(), mime
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if path.exists():
            return path.read_bytes(), mime
        audio = await (_openai(text, model, voice, style) if prov == "openai" else _gemini(text, model, voice, style))
        path.write_bytes(audio)
        return audio, mime


async def _openai(text: str, model: str, voice: str, style: str) -> bytes:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    kwargs = dict(model=model, voice=voice, input=text, response_format="mp3")
    if model.startswith("gpt-"):          # tts-1 / tts-1-hd non accettano 'instructions'
        kwargs["instructions"] = style
    r = await client.audio.speech.create(**kwargs)
    return r.content if hasattr(r, "content") else await r.aread()


async def _gemini(text: str, model: str, voice: str, style: str) -> bytes:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    r = await client.aio.models.generate_content(
        model=model, contents=f"{style}\n\nTesto da leggere:\n{text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
    part = r.candidates[0].content.parts[0]
    data = part.inline_data.data
    mime = (part.inline_data.mime_type or "").lower()
    if "wav" in mime:
        return data
    rate = 24000
    for tok in mime.split(";"):
        if tok.strip().startswith("rate="):
            rate = int(tok.strip()[5:])
    return _wav(data, rate)
