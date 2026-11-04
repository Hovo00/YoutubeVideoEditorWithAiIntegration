"""Calibrate Piper voices against Azure so durations line up.

    .venv/bin/python scripts/calibrate_tts.py              # 3 Azure calls, ~5,250 chars
    .venv/bin/python scripts/calibrate_tts.py --no-azure   # reuse stored Azure numbers

1. Synthesizes scripts/calibration_text.txt with Azure Dmitry at 0.9x, 1.0x
   and 1.1x and records how long each one is (0.95x and 1.05x are
   interpolated). That's how the app predicts Azure's duration at a given
   speed.
2. For every downloaded Piper voice, searches for the "pace" multiplier
   that makes Piper at 1.0x as long as Azure Dmitry at 1.0x.
3. Writes everything to tts_calibration.json, which the app re-reads
   automatically (no restart needed).

Needs AZURE_SPEECH_KEY / AZURE_SPEECH_REGION in the environment (same as the
app) unless --no-azure is given.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import azure_tts, tts  # noqa: E402
from backend.duration_fit import AUTO_RATES  # noqa: E402
from backend.render import get_duration  # noqa: E402

AZURE_REFERENCE_VOICE = "ru-RU-DmitryNeural"
TEXT = (ROOT / "scripts" / "calibration_text.txt").read_text(encoding="utf-8").strip()


MEASURED_RATES = (0.9, 1.0, 1.1)


def interpolate(measured: dict[float, float], rate: float) -> float:
    if rate in measured:
        return measured[rate]
    low = max(r for r in measured if r < rate)
    high = min(r for r in measured if r > rate)
    t = (rate - low) / (high - low)
    return measured[low] + t * (measured[high] - measured[low])


def wav_duration(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def piper_duration(voice: str, pace: float, tmp: Path) -> float:
    out = str(tmp / "piper.wav")
    tts.synthesize_to_wav(TEXT, voice, out, rate=1.0, pace=pace)
    return wav_duration(out)


def find_pace(voice: str, target: float, tmp: Path) -> float:
    """Duration grows monotonically with pace, so bisect on it."""
    low, high = 0.6, 2.0
    pace = 1.0
    for _ in range(12):
        pace = (low + high) / 2
        duration = piper_duration(voice, pace, tmp)
        if abs(duration - target) < 0.2:
            break
        if duration < target:
            low = pace
        else:
            high = pace
    return round(pace, 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-azure", action="store_true", help="reuse Azure durations already in tts_calibration.json")
    args = parser.parse_args()

    calibration = tts.load_calibration().copy()
    azure = calibration.setdefault("azure_durations", {})

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        if not args.no_azure:
            measured = {}
            for rate in MEASURED_RATES:
                out = str(tmp / f"azure_{rate}.mp3")
                azure_tts.synthesize_to_file(TEXT, AZURE_REFERENCE_VOICE, out, rate=rate)
                measured[rate] = get_duration(out)
                print(f"Azure {AZURE_REFERENCE_VOICE} @ {rate:.2f}x: {measured[rate]:.1f}s")
            azure[AZURE_REFERENCE_VOICE] = {
                f"{rate:.2f}": round(interpolate(measured, rate), 3) for rate in AUTO_RATES
            }
            calibration.pop("_note", None)

        reference = azure.get(AZURE_REFERENCE_VOICE, {})
        if "1.00" not in reference:
            sys.exit("No Azure 1.00x duration recorded yet — run without --no-azure first.")
        target = reference["1.00"]
        print(f"Target (Azure 1.00x): {target:.1f}s")

        paces = {}
        for voice in tts.list_available_voices():
            name = voice["name"]
            if not name.startswith("ru_"):
                continue  # the calibration text is Russian
            paces[name] = find_pace(name, target, tmp)
            print(f"Piper {name}: pace {paces[name]:.3f} -> {piper_duration(name, paces[name], tmp):.1f}s")
        calibration["piper_pace"] = {**calibration.get("piper_pace", {}), **paces}

    calibration["calibration_text_chars"] = len(TEXT)
    tts.CALIBRATION_FILE.write_text(json.dumps(calibration, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {tts.CALIBRATION_FILE}")


if __name__ == "__main__":
    main()
