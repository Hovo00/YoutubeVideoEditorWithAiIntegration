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
import shutil
import subprocess
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[float, str], None]

DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL_SIZE", "small")

# Jetson's CUDA-enabled torch build needs two extra things on the dynamic
# linker's search path, beyond whatever the `whisper` process would normally
# pick up (see ~/whisper-venv/bin/activate on a validated Jetson setup):
#   1. The system JetPack CUDA toolkit's cuBLAS (not Jetson/iGPU-specific in
#      the pip-distributed wheel, so it must come from the OS install).
#   2. The pip-installed `nvidia-cudss-cu12` package's own lib/ directory
#      (cuDSS isn't part of the base CUDA toolkit at all) — this one lives
#      *inside whichever venv provides the `whisper` binary*, which isn't
#      necessarily the same venv running this FastAPI process, so it has to
#      be located relative to that binary's own path, not hardcoded.
# Jetson detection is via the standard Tegra release marker file, no extra
# dependency needed.
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


def _whisper_venv_nvidia_lib_dirs() -> list[str]:
    """Finds <venv-root>/lib/python*/site-packages/nvidia/*/lib for
    whichever venv actually provides the `whisper` binary on PATH — that's
    where pip-installed packages like nvidia-cudss-cu12 put their .so files.
    Returns [] if `whisper` isn't found or doesn't look like it's inside a
    venv (e.g. a system-wide install with no such directory)."""

    whisper_bin = shutil.which("whisper")
    if not whisper_bin:
        return []

    venv_root = Path(whisper_bin).resolve().parent.parent
    return [str(p) for p in venv_root.glob("lib/python3.*/site-packages/nvidia/*/lib")]


def _whisper_env() -> dict:
    env = os.environ.copy()
    # Whisper's stdout is a pipe here, so Python would buffer it in large
    # blocks and the per-segment progress lines would arrive late or only at
    # the very end.
    env["PYTHONUNBUFFERED"] = "1"
    if _is_jetson():
        lib_paths = [_JETSON_CUDA_LIB_PATH, *_whisper_venv_nvidia_lib_dirs()]
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join([*lib_paths, existing]) if existing else ":".join(lib_paths)
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


_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def video_id_from_url(url: str) -> str | None:
    """The 11-character YouTube video ID, so the same video is recognized
    regardless of URL form or extra params (&t=, &list=, youtu.be/...).
    None for anything not recognized as a YouTube link."""
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


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
        # Cap at 1080p and prefer VP9/H.264 over AV1: 4K AV1 can't be
        # decoded by older GPUs (e.g. GTX 10-series), so every render had
        # to decode 4K on the CPU — the main reason renders were slow.
        "-S", "res:1080,vcodec:vp9",
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


# Whisper prints each segment as "[MM:SS.mmm --> MM:SS.mmm] text", with an
# "HH:" prefix only once the audio passes an hour, so hours are optional.
_SEGMENT_END_RE = re.compile(
    r"\[(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3}\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})\]"
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

    # Deliberately do NOT pass --device/--fp16 here. The `whisper` binary on
    # PATH can live in a completely different Python environment/venv than
    # the one running this FastAPI process (e.g. a dedicated venv with a
    # hand-tuned CUDA/torch install) — checking torch.cuda.is_available() in
    # *this* process and forcing that choice onto the subprocess would
    # silently discard a perfectly working GPU setup in the subprocess's own
    # environment whenever the orchestrating process itself lacks torch.
    # Omitting both flags lets Whisper auto-detect CUDA vs CPU (and fp16
    # support) using whichever environment actually provides the binary.
    command = [
        "whisper", str(audio_path),
        "--model", model_size,
        "--language", language,
        "--task", "transcribe",
        "--output_format", "vtt",
        "--output_dir", str(audio_path.parent),
    ]

    if on_progress:
        on_progress(0.0, "Transcribing… 0%")

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
            "Whisper is not installed — install 'openai-whisper' (pip install "
            "openai-whisper) somewhere on this machine and make sure the "
            "'whisper' command is on PATH for this app (see the setup docs)."
        ) from exc

    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        match = _SEGMENT_END_RE.search(line)
        if match and on_progress and total_duration > 0:
            hours, minutes, seconds, millis = match.groups()
            segment_end = (
                int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
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

    return _add_missing_hours(vtt_path.read_text(encoding="utf-8"))


# Whisper's VTT writer omits the hours field whenever it's zero ("01:23.456"),
# but the rest of the app (parser, AI instructions) expects HH:MM:SS.mmm.
_SHORT_TIMESTAMP_RE = re.compile(r"(?<![\d:])(\d{2}:\d{2}\.\d{3})(?![\d:])")


def _add_missing_hours(vtt_text: str) -> str:
    return "\n".join(
        _SHORT_TIMESTAMP_RE.sub(r"00:\1", line) if "-->" in line else line
        for line in vtt_text.split("\n")
    )
