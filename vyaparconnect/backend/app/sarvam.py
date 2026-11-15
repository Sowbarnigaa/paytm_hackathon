"""Sarvam AI integration (https://docs.sarvam.ai). Every call degrades gracefully: if the key is missing, the
service is slow/down, or the reply is unusable, the functions return None and callers fall back to the rule-based path.

  - Chat   sarvam-105b-conversations : turns free text / speech in any Indian language into a structured order
  - STT    Saaras (saaras:v3)        : speech -> text, language auto-detected (voice procurement)
  - TTS    Bulbul (bulbul:v3)        : text -> speech (read results aloud)
  - Text   Sarvam-Translate          : multilingual output (Sarvam-M is deprecated by Sarvam; translate replaces it)

The API key is read from SARVAM_API_KEY (environment, or the git-ignored vyaparconnect/.env). It is never logged.
Set VC_SARVAM=0 to disable all calls (the test-suite does this).
"""
import base64
import io
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("vyaparconnect.sarvam")

CHAT_MODEL = "sarvam-105b-conversations"     # sarvam-105b spends its whole token budget on reasoning -> empty JSON
STT_MODEL = "saaras:v3"
TTS_MODEL = "bulbul:v3"
TRANSLATE_MODEL = "sarvam-translate:v1"
TIMEOUT = 20
MAX_AUDIO_BYTES = 6 * 1024 * 1024
AUDIO_CODECS = {"webm": "webm", "ogg": "ogg", "mp4": "mp4", "wav": "wav", "mp3": "mp3", "mpeg": "mp3", "x-m4a": "x-m4a", "aac": "aac"}
LANGS = {"en": "en-IN", "ta": "ta-IN", "hi": "hi-IN"}

_client = None


def _load_key() -> str | None:
    key = os.environ.get("SARVAM_API_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parents[2] / ".env"            # vyaparconnect/.env
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "SARVAM_API_KEY":
                return value.strip().strip("\"'") or None
    return None


def enabled() -> bool:
    return os.environ.get("VC_SARVAM", "1") != "0" and bool(_load_key())


def _get():
    global _client
    if _client is None:
        from sarvamai import SarvamAI                                   # imported lazily: the app still boots without the SDK
        _client = SarvamAI(api_subscription_key=_load_key(), timeout=TIMEOUT)
    return _client


# ------------------------------------------------------------------ chat: order extraction

def _json_from(reply: str | None):
    if not reply:
        return None
    m = re.search(r"\{.*\}", reply.replace("```json", "").replace("```", ""), re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def extract_order(text: str, products: list[dict]) -> dict | None:
    """Ask Sarvam-105B to read an order. Returns {"items": [{product, qty, unit}], "budget", "language"} or None.
    The caller must validate the result against the products table - model output is never trusted as-is."""
    if not enabled():
        return None
    names = ", ".join(f'"{p["name"]}"' for p in products)
    system = ("You read wholesale grocery orders from Indian shopkeepers, written or spoken in English, Hindi, Tamil or a mix, "
              "in any script. Reply with ONLY compact JSON, no prose: "
              '{"items":[{"product":str,"qty":number|null,"unit":str|null}],"budget":number|null,"language":"en"|"hi"|"ta"}. '
              f"product MUST be exactly one of these names, without units or brackets: {names}. "
              "Keep qty and unit as the shopkeeper said them (kg, litre, quintal, ton, box...). "
              "qty is null when no quantity is said. budget is a rupee amount or null. Never invent items.")
    try:
        r = _get().chat.completions(model=CHAT_MODEL, temperature=0.1, max_tokens=500,
                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": text[:1000]}])
        data = _json_from(r.choices[0].message.content)
    except Exception:
        log.warning("sarvam chat failed", exc_info=True)
        return None
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else None


# ------------------------------------------------------------------ speech to text (Saaras)

def transcribe(audio: bytes, codec: str) -> dict | None:
    """Speech -> {"text", "language"} with automatic language detection, or None on failure."""
    if not enabled() or not audio or len(audio) > MAX_AUDIO_BYTES or codec not in AUDIO_CODECS:
        return None
    try:
        r = _get().speech_to_text.transcribe(file=("speech." + codec, io.BytesIO(audio), "audio/" + codec), model=STT_MODEL,
                                             mode="codemix", language_code="unknown", input_audio_codec=AUDIO_CODECS[codec])
        text = (r.transcript or "").strip()
    except Exception:
        log.warning("sarvam stt failed", exc_info=True)
        return None
    return {"text": text, "language": (r.language_code or "").split("-")[0]} if text else None


# ------------------------------------------------------------------ translate + text to speech

def translate(text: str, lang: str) -> str | None:
    """English -> Tamil/Hindi with Sarvam-Translate. Returns None on failure."""
    if lang not in ("ta", "hi") or not enabled():
        return None
    try:
        return _get().text.translate(input=text[:1500], source_language_code="en-IN", target_language_code=LANGS[lang],
                                     model=TRANSLATE_MODEL).translated_text
    except Exception:
        log.warning("sarvam translate failed", exc_info=True)
        return None


def speak(text: str, lang: str) -> str | None:
    """Text -> base64 MP3 with Bulbul, or None on failure."""
    if not enabled() or not text.strip():
        return None
    try:
        r = _get().text_to_speech.convert(text=text[:1500], language_code=LANGS.get(lang, "en-IN"), model=TTS_MODEL, output_audio_codec="mp3")
        return r.audios[0]
    except Exception:
        log.warning("sarvam tts failed", exc_info=True)
        return None


def b64decode(data: str) -> bytes | None:
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return None
