"""Microsoft Azure AI Speech text-to-speech — a paid cloud API (500,000
characters/month free, then ~$16 per 1M characters) offering noticeably
more natural voices than the local/free Piper engine, including the
Russian "Dmitry" voice.

Needs AZURE_SPEECH_KEY and AZURE_SPEECH_REGION environment variables — get
them from an Azure Speech resource in the Azure Portal (the free F0 tier
covers this; no code changes needed once they're set).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

# Russian voices currently offered by Azure AI Speech.
KNOWN_VOICES = {
    "ru-RU-DmitryNeural": "Russian (Azure) — Dmitry (male)",
    "ru-RU-SvetlanaNeural": "Russian (Azure) — Svetlana (female)",
    "ru-RU-DariyaNeural": "Russian (Azure) — Dariya (female)",
}

_OUTPUT_FORMAT = "audio-24khz-96kbitrate-mono-mp3"

# Azure's free tier is 500,000 characters/month, reset on the calendar
# month. Tracked here (not under workspace/, which gets wiped on every new
# upload) so usage persists across projects and server restarts.
FREE_TIER_CHAR_LIMIT = 500_000
_USAGE_FILE = Path(__file__).resolve().parent.parent / "azure_tts_usage.json"


class AzureNotConfiguredError(RuntimeError):
    pass


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _load_usage() -> dict:
    if _USAGE_FILE.exists():
        try:
            data = json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
            if data.get("month") == _current_month():
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"month": _current_month(), "characters_used": 0}


def _record_usage(char_count: int) -> None:
    data = _load_usage()
    data["characters_used"] += char_count
    _USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")


def get_usage() -> dict:
    data = _load_usage()
    return {
        "month": data["month"],
        "characters_used": data["characters_used"],
        "free_tier_limit": FREE_TIER_CHAR_LIMIT,
    }


def is_configured() -> bool:
    return bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))


def list_available_voices() -> list[dict]:
    if not is_configured():
        return []
    return [{"name": name, "label": label} for name, label in KNOWN_VOICES.items()]


def synthesize_to_file(text: str, voice_name: str, output_path: str) -> None:
    api_key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    if not api_key or not region:
        raise AzureNotConfiguredError(
            "Azure TTS isn't configured — set the AZURE_SPEECH_KEY and "
            "AZURE_SPEECH_REGION environment variables (see an Azure Speech "
            "resource in the Azure Portal) and restart the app."
        )

    ssml = (
        '<speak version="1.0" xml:lang="ru-RU">'
        f'<voice name="{voice_name}">{escape(text)}</voice>'
        "</speak>"
    )

    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    request = urllib.request.Request(
        url,
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": _OUTPUT_FORMAT,
            "User-Agent": "VideoEditorY",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            audio_bytes = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure TTS request failed ({exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Azure TTS: {exc.reason}") from exc

    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    _record_usage(len(text))
