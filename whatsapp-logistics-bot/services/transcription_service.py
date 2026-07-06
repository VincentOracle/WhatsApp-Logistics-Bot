"""
Speech-to-text for WhatsApp voice notes, using OpenAI's Whisper API.
WhatsApp voice notes arrive from Twilio as audio/ogg (opus codec);
Whisper accepts ogg directly so no transcoding step is required.
"""
import io

from openai import OpenAI

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


def transcribe_audio(audio_bytes: bytes, filename: str = "voice_note.ogg") -> str:
    """
    Transcribe a voice note to text. Returns an empty string (and logs
    a warning) on any failure so the caller can gracefully ask the user
    to type their message instead.
    """
    if Config.using_placeholder_openai_key():
        logger.warning("OPENAI_API_KEY is a placeholder — cannot transcribe voice notes.")
        return ""

    try:
        client = _get_client()
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        transcript = client.audio.transcriptions.create(
            model=Config.WHISPER_MODEL,
            file=audio_file,
        )
        return (transcript.text or "").strip()
    except Exception:
        logger.exception("Voice note transcription failed.")
        return ""
