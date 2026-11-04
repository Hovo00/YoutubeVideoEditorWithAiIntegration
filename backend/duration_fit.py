"""Pick a TTS speed so a chunk's voice-over fills its video window.

Automatic TTS first renders each chunk with a free local Piper voice. Piper
is calibrated so its 1.0x lasts about as long as Azure's 1.0x (see
scripts/calibrate_tts.py), so that render predicts the paid Azure
duration. From that prediction we choose one of AUTO_RATES, and only then
spend Azure characters. Chunks that can't fit are flagged for the user to
edit instead of being sent to Azure.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tts import load_calibration

AUTO_RATES = (0.9, 0.95, 1.0, 1.05, 1.1)

# Never leave more than this much silence at the end of a chunk's window.
MAX_GAP_SECONDS = 5.0

# Estimates are approximate (Piper's timing alone varies by ~2% between
# runs of the same text), so aim this far under the window: a fixed part
# plus a fraction of the window. Then a slightly optimistic estimate rarely
# overflows and costs an Azure retry.
FIT_MARGIN_SECONDS = 0.3
FIT_MARGIN_FRACTION = 0.015

# Real audio may run over the window by this much and still count as fitting
# (same tolerance as the manual per-chunk check).
OVERFLOW_TOLERANCE_SECONDS = 0.05

_AZURE_REFERENCE_VOICE = "ru-RU-DmitryNeural"


def rate_factor(azure_voice: str | None, rate: float) -> float:
    """How a speed changes the duration, relative to 1.0x.

    For Azure voices this uses the durations measured during calibration
    (Azure's prosody rate isn't exactly inversely proportional to the
    duration). Uncalibrated voices fall back to the reference voice, then
    to plain 1/rate. Piper voices pass None, since Piper scales exactly 1/rate."""
    if azure_voice is not None:
        durations = load_calibration().get("azure_durations", {})
        measured = durations.get(azure_voice) or durations.get(_AZURE_REFERENCE_VOICE) or {}
        at_rate = measured.get(f"{rate:.2f}")
        at_one = measured.get("1.00")
        if at_rate and at_one:
            return at_rate / at_one
    return 1.0 / rate


@dataclass
class RateChoice:
    rate: float
    estimate: float  # predicted seconds of audio at `rate`
    verdict: str  # "ok" | "too_long" | "too_short"


def choose_rate(duration_1x: float, window: float, azure_voice: str | None) -> RateChoice:
    """Slowest speed whose predicted duration still fits the window. That
    leaves the smallest gap after the voice-over."""
    estimates = {rate: duration_1x * rate_factor(azure_voice, rate) for rate in AUTO_RATES}
    target = window - FIT_MARGIN_SECONDS - FIT_MARGIN_FRACTION * window
    fitting = [rate for rate in AUTO_RATES if estimates[rate] <= target]

    if not fitting:
        fastest = max(AUTO_RATES)
        return RateChoice(fastest, estimates[fastest], "too_long")

    rate = min(fitting)
    if window - estimates[rate] > MAX_GAP_SECONDS:
        return RateChoice(rate, estimates[rate], "too_short")
    return RateChoice(rate, estimates[rate], "ok")


def next_faster_rate(rate: float) -> float | None:
    faster = [r for r in AUTO_RATES if r > rate]
    return min(faster) if faster else None


def judge_actual(audio_duration: float, window: float) -> str:
    if audio_duration > window + OVERFLOW_TOLERANCE_SECONDS:
        return "too_long"
    if window - audio_duration > MAX_GAP_SECONDS:
        return "too_short"
    return "ok"
