"""Local, free text-to-speech via Piper (https://github.com/rhasspy/piper).

Runs entirely on-device — no API key, no network calls, no per-request
cost. Voice models are .onnx files downloaded once into tts_voices/ (see
`python3 -m piper.download_voices <name> --data-dir tts_voices`) and kept
loaded in memory after first use so repeat chunks are fast.
"""

from __future__ import annotations

import wave
from pathlib import Path

from piper import PiperVoice

VOICES_DIR = Path(__file__).resolve().parent.parent / "tts_voices"

# Known voice names -> human label. Only the ones with a downloaded .onnx
# file in VOICES_DIR are actually offered (see list_available_voices).
KNOWN_VOICES = {
    "ru_RU-irina-medium": "Russian — Irina (female)",
    "ru_RU-dmitri-medium": "Russian — Dmitri (male)",
    "ru_RU-denis-medium": "Russian — Denis (male)",
    "ru_RU-ruslan-medium": "Russian — Ruslan (male)",
    "en_US-ryan-medium": "English (US) — Ryan (male)",
}

_loaded_voices: dict[str, PiperVoice] = {}


class VoiceNotAvailableError(RuntimeError):
    pass


def list_available_voices() -> list[dict]:
    return [
        {"name": name, "label": label}
        for name, label in KNOWN_VOICES.items()
        if (VOICES_DIR / f"{name}.onnx").exists()
    ]


def _get_voice(voice_name: str) -> PiperVoice:
    if voice_name not in _loaded_voices:
        model_path = VOICES_DIR / f"{voice_name}.onnx"
        if not model_path.exists():
            raise VoiceNotAvailableError(
                f"Voice '{voice_name}' isn't downloaded yet. Run: "
                f"python3 -m piper.download_voices {voice_name} --data-dir tts_voices"
            )
        _loaded_voices[voice_name] = PiperVoice.load(str(model_path))

    return _loaded_voices[voice_name]


def synthesize_to_wav(text: str, voice_name: str, output_path: str) -> None:
    voice = _get_voice(voice_name)

    with wave.open(output_path, "wb") as wav_file:
        params_set = False
        for chunk in voice.synthesize(text):
            if not params_set:
                wav_file.setframerate(chunk.sample_rate)
                wav_file.setsampwidth(chunk.sample_width)
                wav_file.setnchannels(chunk.sample_channels)
                params_set = True
            wav_file.writeframes(chunk.audio_int16_bytes)
