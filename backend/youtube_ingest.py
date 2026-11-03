"""YouTube download + Whisper transcription — the only place in the app
that touches yt-dlp, the audio-extraction ffmpeg call, and the `whisper`
CLI.

Everything here shells out to external tools via subprocess (same
convention as render.py's ffmpeg/ffprobe wrappers) rather than importing
`whisper`/`torch` in-process: a crash or CUDA-init failure in a subprocess
just becomes a normal error the caller catches, instead of potentially
taking down the whole FastAPI server. It also makes the Jetson-specific
`LD_LIBRARY_PATH` override a clean per-subprocess `env=` dict instead of a
process-wide mutation, and guarantees GPU memory is fully released the
instant the subprocess exits.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[float, str], None]

DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL_SIZE", "small")

# Jetson's CUDA-enabled torch build needs the system JetPack CUDA toolkit's
# cuBLAS ahead of the pip-distributed one on the dynamic linker's search
# path (see ~/whisper-venv/bin/activate on a validated Jetson setup) —
# detected via the standard Tegra release marker file, no extra dependency.
_JETSON_MARKER = Path("/etc/nv_tegra_release")
_JETSON_CUDA_LIB_PATH = "/usr/local/cuda-12.6/targets/aarch64-linux/lib"


class DownloadError(RuntimeError):
    """yt-dlp failed: bad URL, private/deleted/geo-blocked/age-restricted
    video, missing binary, or a network error."""


class TranscriptionError(RuntimeError):
    """Audio extraction or Whisper itself failed: missing dependency, OOM,
    corrupt/empty audio, or a bad language code."""


def _is_jetson() -> bool:
    return _JETSON_MARKER.exists()


def _select_device() -> str:
    """Returns 'cuda' if available, defensively falling back to 'cpu' on
    any failure (including torch itself failing to import) so a broken
    local CUDA/torch install degrades to slow-but-working CPU transcription
    instead of crashing ingestion before it starts."""

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _whisper_env() -> dict:
    env = os.environ.copy()
    if _is_jetson():
        env["LD_LIBRARY_PATH"] = (
            f"{_JETSON_CUDA_LIB_PATH}:{env.get('LD_LIBRARY_PATH', '')}"
        )
    return env


_DOWNLOAD_PCT_RE = re.compile(r"(\d{1,3}\.\d)%")

_YTDLP_ERROR_PATTERNS = [
    (re.compile(r"is not a valid URL", re.IGNORECASE), "That doesn't look like a valid YouTube URL."),
    (re.compile(r"Private video", re.IGNORECASE), "This video is private or has been removed."),
    # yt-dlp's actual wording varies ("Video unavailable", "This video is
    # unavailable", "video is no longer available") — match loosely on the
    # "video" ... "unavailable"/"removed" combination rather than one exact
    # phrase, confirmed against real yt-dlp output during testing.
    (re.compile(r"video (?:is )?(?:no longer )?(?:unavailable|has been removed)", re.IGNORECASE), "This video is private, deleted, or otherwise unavailable."),
    (re.compile(r"not available in your country|blocked it", re.IGNORECASE), "This video is not available in your region."),
    (re.compile(r"Sign in to confirm your age", re.IGNORECASE), "This video is age-restricted and can't be downloaded without a signed-in YouTube account."),
    (re.compile(r"Sign in to confirm you're not a bot", re.IGNORECASE), "YouTube is blocking automated downloads from this network right now — try again later or from a different network."),
    (re.compile(r"Unable to download webpage|getaddrinfo failed|Temporary failure in name resolution|Network is unreachable", re.IGNORECASE), "Could not reach YouTube — check your internet connection and try again."),
]


def _classify_ytdlp_failure(output: str) -> str:
    for pattern, message in _YTDLP_ERROR_PATTERNS:
        if pattern.search(output):
            return message
    tail = "\n".join(output.strip().splitlines()[-5:])
    return f"yt-dlp failed: {tail or 'unknown error'}"


def download_video(url: str, dest_dir: Path, on_progress: ProgressCallback) -> Path:
    """Downloads the best available video+audio as an mp4 (falling back to
    a single combined format if a separate-streams merge isn't available)
    into dest_dir/video.<ext>, reporting approximate percentage progress
    parsed from yt-dlp's own stdout."""

    dest_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(dest_dir / "video.%(ext)s")

    command = [
        "yt-dlp",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "--newline",
        "-o", output_template,
        url,
    ]

    lines: list[str] = []
    try:
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except FileNotFoundError as exc:
        raise DownloadError(
            "yt-dlp was not found — install it and make sure it is on PATH."
        ) from exc

    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        match = _DOWNLOAD_PCT_RE.search(line)
        if match:
            pct = float(match.group(1))
            on_progress(min(pct / 100, 0.99), f"Downloading… {pct:.0f}%")

    proc.wait()
    if proc.returncode != 0:
        raise DownloadError(_classify_ytdlp_failure("".join(lines)))

    matches = sorted(dest_dir.glob("video.*"))
    if not matches:
        raise DownloadError("yt-dlp reported success but no video file was found.")
    return matches[0]


def extract_audio(video_path: Path, dest_dir: Path) -> Path:
    """ffmpeg -vn -ar 16000 -ac 1 -c:a pcm_s16le — 16kHz mono PCM, Whisper's
    native format (Whisper resamples internally regardless, but this skips
    redundant work and matches the validated manual workflow)."""

    audio_path = dest_dir / "audio.wav"
    command = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(audio_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TranscriptionError(
            "ffmpeg was not found — install it and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise TranscriptionError(
            f"Could not extract audio from the downloaded video: {exc.stderr}"
        ) from exc

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise TranscriptionError(
            "The downloaded video has no usable audio track to transcribe."
        )

    return audio_path


_SEGMENT_END_RE = re.compile(
    r"\[\d{1,2}:\d{2}:\d{2}\.\d{3}\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})\]"
)

_WHISPER_ERROR_PATTERNS = [
    (re.compile(r"CUDA out of memory|RuntimeError: .*memory", re.IGNORECASE), "Transcription ran out of memory. Try a smaller Whisper model (see the setup docs) or close other applications."),
    (re.compile(r"is not a valid language|unsupported language", re.IGNORECASE), "That language isn't recognized by Whisper — pick a different option."),
    (re.compile(r"Killed", re.IGNORECASE), "Transcription was killed by the operating system, likely due to running out of memory."),
]


def _classify_whisper_failure(output: str) -> str:
    for pattern, message in _WHISPER_ERROR_PATTERNS:
        if pattern.search(output):
            return message
    tail = "\n".join(output.strip().splitlines()[-8:])
    return f"Whisper failed: {tail or 'unknown error'}"


def transcribe(
    audio_path: Path,
    language: str,
    model_size: str = DEFAULT_WHISPER_MODEL,
    on_progress: ProgressCallback | None = None,
) -> str:
    """Runs the `whisper` CLI and returns the resulting VTT text. Reports
    approximate progress by parsing each segment's end-timestamp from
    Whisper's own stdout against the audio's total duration."""

    from .render import FFmpegNotFoundError, get_duration

    try:
        total_duration = get_duration(str(audio_path))
    except FFmpegNotFoundError as exc:
        raise TranscriptionError(str(exc)) from exc

    device = _select_device()
    if on_progress and device == "cpu":
        on_progress(0.0, "Transcribing on CPU (GPU unavailable) — this will be slower.")

    command = [
        "whisper", str(audio_path),
        "--model", model_size,
        "--language", language,
        "--task", "transcribe",
        "--output_format", "vtt",
        "--output_dir", str(audio_path.parent),
        "--device", device,
        "--fp16", "True" if device == "cuda" else "False",
    ]

    lines: list[str] = []
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=_whisper_env(),
        )
    except FileNotFoundError as exc:
        raise TranscriptionError(
            "Whisper is not installed — run 'pip install openai-whisper' in "
            "this app's virtual environment."
        ) from exc

    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        match = _SEGMENT_END_RE.search(line)
        if match and on_progress and total_duration > 0:
            hours, minutes, seconds, millis = match.groups()
            segment_end = (
                int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
            )
            fraction = min(segment_end / total_duration, 0.99)
            on_progress(fraction, f"Transcribing… {fraction * 100:.0f}%")

    proc.wait()
    if proc.returncode != 0:
        raise TranscriptionError(_classify_whisper_failure("".join(lines)))

    vtt_path = audio_path.with_suffix(".vtt")
    if not vtt_path.exists():
        raise TranscriptionError(
            "Whisper finished but did not produce a transcript file."
        )

    return vtt_path.read_text(encoding="utf-8")
