"""
Audio message handler for the WhatsApp bot.

Downloads voice notes from Meta's media API, transcribes them via OpenAI
Whisper if OPENAI_API_KEY is set, then routes the transcript through the
normal text pipeline (so audio leads enter the sales agent / RAG / commands
just like typed messages).

If transcription is unavailable, sends a polite fallback so we never ghost
audio-only senders again (lead #37 sent 96 voice notes that were silently
ignored — that bug stops here).
"""
from __future__ import annotations

import logging
import os
import httpx

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"

FALLBACK_MSG = (
    "¡Hola! 🎙️ Recibí tu mensaje de voz pero por ahora solo puedo leer texto. "
    "¿Me puedes escribir tu pregunta? Por ejemplo: el modelo de tu celular y "
    "qué tipo de funda buscas."
)


async def fetch_media_url(media_id: str) -> str | None:
    """Step 1: get the temporary download URL from Meta."""
    if not WHATSAPP_TOKEN or not media_id:
        return None
    h = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://graph.facebook.com/v21.0/{media_id}", headers=h)
            if r.status_code == 200:
                return r.json().get("url")
            logger.warning(f"media meta fetch failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.warning(f"media meta fetch err: {e}")
    return None


async def download_media(url: str) -> bytes | None:
    if not url or not WHATSAPP_TOKEN:
        return None
    h = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=h)
            if r.status_code == 200:
                return r.content
            logger.warning(f"media download failed: {r.status_code}")
    except Exception as e:
        logger.warning(f"media download err: {e}")
    return None


async def transcribe(audio_bytes: bytes) -> str | None:
    if not OPENAI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                WHISPER_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
                data={"model": WHISPER_MODEL, "language": "es"},
            )
            if r.status_code == 200:
                return (r.json().get("text") or "").strip()
            logger.warning(f"whisper failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.warning(f"whisper err: {e}")
    return None


async def handle_audio(from_number: str, audio_id: str) -> str | None:
    """
    Returns the transcript on success, or None if unavailable.
    Caller is responsible for sending the fallback message + routing the
    transcript through process_text_message.
    """
    media_url = await fetch_media_url(audio_id)
    if not media_url:
        return None
    audio_bytes = await download_media(media_url)
    if not audio_bytes:
        return None
    return await transcribe(audio_bytes)
