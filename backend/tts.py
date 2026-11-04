"""Local, free text-to-speech via Piper (https://github.com/rhasspy/piper).

Runs entirely on-device — no API key, no network calls, no per-request
cost. Voice models are .onnx files downloaded once into tts_voices/ (see
`python3 -m piper.download_voices <name> --data-dir tts_voices`) and kept
loaded in memory after first use so repeat chunks are fast.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

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

# Piper's stock pacing is noticeably faster than Azure's neural voices, and
# Piper voices also differ a lot from each other. Every Piper voice is
# calibrated so that its 1.0x takes about as long as Azure Dmitry at 1.0x on
# the same text (see scripts/calibrate_tts.py). That's what lets a free
# Piper render predict how long a paid Azure render will be.
#  - BASE_LENGTH_SCALE stretches every phoneme (>1 = slower speech).
#  - BASE_SENTENCE_PAUSE_SECONDS inserts silence between sentences (Piper
#    otherwise glues sentences together with almost no gap).
# Both get multiplied by a per-voice "pace" from tts_calibration.json, then
# divided by the requested speed `rate` (1.2 = faster, 0.8 = slower).
BASE_LENGTH_SCALE = 1.12
BASE_SENTENCE_PAUSE_SECONDS = 0.45

CALIBRATION_FILE = Path(__file__).resolve().parent.parent / "tts_calibration.json"
_calibration_cache: tuple[float, dict] | None = None


def load_calibration() -> dict:
    """Contents of tts_calibration.json (re-read when the file changes, so a
    fresh calibration takes effect without restarting the app)."""
    global _calibration_cache
    try:
        mtime = CALIBRATION_FILE.stat().st_mtime
    except OSError:
        return {}
    if _calibration_cache is None or _calibration_cache[0] != mtime:
        try:
            data = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        _calibration_cache = (mtime, data)
    return _calibration_cache[1]


def piper_pace(voice_name: str) -> float:
    return float(load_calibration().get("piper_pace", {}).get(voice_name, 1.0))


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


def synthesize_to_wav(
    text: str, voice_name: str, output_path: str, rate: float = 1.0, pace: float | None = None
) -> None:
    """`pace` overrides the calibrated per-voice pace (used by the
    calibration script while it searches for the right value)."""
    voice = _get_voice(voice_name)
    rate = rate if rate > 0 else 1.0
    stretch = (piper_pace(voice_name) if pace is None else pace) / rate
    syn_config = SynthesisConfig(length_scale=BASE_LENGTH_SCALE * stretch)

    with wave.open(output_path, "wb") as wav_file:
        params_set = False
        pause_bytes = b""
        for chunk in voice.synthesize(text, syn_config=syn_config):
            if not params_set:
                wav_file.setframerate(chunk.sample_rate)
                wav_file.setsampwidth(chunk.sample_width)
                wav_file.setnchannels(chunk.sample_channels)
                pause_frames = int(chunk.sample_rate * BASE_SENTENCE_PAUSE_SECONDS * stretch)
                pause_bytes = b"\x00" * (pause_frames * chunk.sample_width * chunk.sample_channels)
                params_set = True
            else:
                # Pause *between* sentences only — no trailing silence.
                wav_file.writeframes(pause_bytes)
            wav_file.writeframes(chunk.audio_int16_bytes)
