"""Footage for added parts (B-roll).

An added part (Mode 4) has no video of its own: the edited video pauses while
its voice-over plays. The user can fill that pause with clips picked from the
main video or from any number of extra YouTube videos. Only their picture is
used — the voice-over is the audio.

A project's sources live in project["sources"] (source_id -> dict), and each
addition dict holds its picks in addition["clips"] as
[{"source_id", "start", "end"}], in play order.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import youtube_ingest
from .render import get_duration

MAIN_SOURCE_ID = "main"

# Thumbnails in a source's timeline strip.
FILMSTRIP_TILES = 60
FILMSTRIP_TILE_HEIGHT = 90
FILMSTRIP_NAME = "filmstrip.jpg"

# Speech rate used to guess a part's length when no local voice is
# installed to measure it (~140 words per minute).
WORDS_PER_SECOND = 2.33


def _grab_frame(video_path: str, time: float, out_path: Path) -> bool:
    command = [
        "ffmpeg", "-y", "-v", "error",
        # Keyframes only: the seek lands on the keyframe before `time`, and
        # nothing after it has to be decoded. Close enough for a thumbnail.
        "-skip_frame", "nokey",
        "-ss", f"{time:.3f}", "-i", video_path,
        "-frames:v", "1", "-vf", f"scale=-2:{FILMSTRIP_TILE_HEIGHT}", "-q:v", "5",
        str(out_path),
    ]
    subprocess.run(command, capture_output=True)
    return out_path.exists()


def make_filmstrip(video_path: str, duration: float, out_path: Path) -> None:
    """One wide JPEG of FILMSTRIP_TILES evenly spaced frames, drawn under the
    picker's timeline. Each frame is a separate seek (a fraction of a second
    each, run in parallel), so it takes about the same time for a 5-minute
    video as for a 2-hour one — decoding the whole video would not."""
    step = duration / FILMSTRIP_TILES
    with tempfile.TemporaryDirectory() as tmp:
        tiles = [Path(tmp) / f"tile_{i:03d}.jpg" for i in range(FILMSTRIP_TILES)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            ok = list(pool.map(lambda i: _grab_frame(video_path, (i + 0.5) * step, tiles[i]), range(FILMSTRIP_TILES)))
        if not any(ok):
            raise RuntimeError("Could not read any frames for the filmstrip.")
        # A failed seek (e.g. right at the end) reuses its neighbour, so the
        # numbered sequence has no gaps for ffmpeg's image reader.
        last_good = tiles[ok.index(True)]
        for tile, good in zip(tiles, ok):
            if good:
                last_good = tile
            else:
                shutil.copyfile(last_good, tile)
        command = [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(Path(tmp) / "tile_%03d.jpg"),
            "-vf", f"tile={FILMSTRIP_TILES}x1", "-frames:v", "1", "-q:v", "5",
            str(out_path),
        ]
        subprocess.run(command, check=True, capture_output=True)


def filmstrip_path(video_path: str) -> Path:
    # Next to the video, so a video in the library keeps its strip too.
    return Path(video_path).parent / FILMSTRIP_NAME


def ensure_filmstrip(video_path: str, duration: float) -> Path | None:
    path = filmstrip_path(video_path)
    if not path.exists():
        try:
            make_filmstrip(video_path, duration, path)
        except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError):
            return None
    return path


def new_source(url: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "url": url,
        "title": url,
        "status": "downloading",
        "progress": 0.0,
        "message": "Queued…",
        "error": None,
        "path": None,
        "duration": None,
        "has_filmstrip": False,
    }


def download_source(source: dict, library_dir: Path, fallback_dir: Path) -> None:
    """Runs in a thread. Uses the same per-video library cache as the main
    ingest, so a video that was already downloaded isn't fetched again."""

    def on_progress(frac: float, message: str) -> None:
        source["progress"] = frac
        source["message"] = message

    try:
        video_id = youtube_ingest.video_id_from_url(source["url"])
        target_dir = library_dir / video_id if video_id else fallback_dir / source["id"]
        cached = sorted(p for p in target_dir.glob("video.*")) if target_dir.exists() else []
        if cached:
            video_path = cached[0]
        else:
            # Download into a scratch folder first: a failed download can leave
            # partial files that must not look like a cached video.
            scratch = fallback_dir / f"_download_{source['id']}"
            downloaded = youtube_ingest.download_video(source["url"], scratch, on_progress)
            target_dir.mkdir(parents=True, exist_ok=True)
            video_path = target_dir / f"video{downloaded.suffix}"
            downloaded.replace(video_path)
            shutil.rmtree(scratch, ignore_errors=True)

        source["message"] = "Preparing timeline…"
        duration = get_duration(str(video_path))
        source["path"] = str(video_path)
        source["duration"] = duration
        source["has_filmstrip"] = ensure_filmstrip(str(video_path), duration) is not None
        if video_id:
            source["title"] = f"YouTube {video_id}"
        source["status"] = "ready"
        source["progress"] = 1.0
        source["message"] = ""
    except Exception as exc:  # shown on the source's chip in the picker
        source["status"] = "error"
        source["error"] = str(exc)


def estimate_seconds(text: str, synthesize) -> float:
    """How long the part's voice-over will roughly run. `synthesize(text)`
    returns the length of a local (free) rendering, or None when there's no
    local voice; then fall back to a words-per-minute guess."""
    measured = None
    try:
        measured = synthesize(text)
    except Exception:
        measured = None
    if measured:
        return measured
    return max(1.0, len(text.split()) / WORDS_PER_SECOND)


def clip_inputs(clips: list[dict], sources: dict[str, dict]) -> list[tuple[str, float, float]]:
    """(video path, start, end) for every clip whose source is ready."""
    resolved = []
    for clip in clips or []:
        source = sources.get(clip.get("source_id"))
        if not source or source.get("status") != "ready" or not source.get("path"):
            continue
        start, end = float(clip["start"]), float(clip["end"])
        if end - start > 0.05:
            resolved.append((source["path"], start, end))
    return resolved
