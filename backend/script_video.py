"""Work type 3: a new video from a script ("Video from a script").

There's no source video to edit here. Claude (Mode 6 in
AI_EDITING_INSTRUCTIONS.md) researches the topic or uses the user's
resources, writes the script split into scenes and picks real footage and
photos for every scene into workspace/script_video/shots.md. The app then:

  1. downloads every video (whole, into the shared per-video library cache)
     and image the shots point at,
  2. makes timestamped contact sheets of every video so Claude can check
     and fix the clip timings (sheets/ — a second, optional Claude pass),
  3. voices each scene's text (Piper or Azure) and renders: each scene's
     shots are cut/zoomed to 1920x1080, fitted to its voice-over, with
     captions/titles, optional music, loudness-normalized.

shots.md format (see Mode 6 for the full rules Claude follows):

    # Video title

    ## Scene 1 | Short scene name
    The text read aloud for this scene (one or more paragraphs).

    - video | https://www.youtube.com/watch?v=... | 0:50.0-0:52.8 | crop
    - image | https://commons.wikimedia.org/wiki/File:X.jpg | 3 | caption: Name
    - video | https://youtu.be/... | 1:04-1:10 | title: РАУНД 1

    ## CREDITS
    - free text, copied into the credits file next to the render

Shot options: `crop` (cut off the bottom of the frame — a lower-third
scoreboard or someone's logo), `caption: …` (lower-third text), `title: …`
(big label in the top-left for the first seconds), `zoom: in|out` (images).
Video clips play at most MAX_CLIP_SECONDS (4.5 s) each, zoomed in 10%
with a light colour look; photos take up whatever time the scene's
voice-over needs beyond its clips (see fit_lengths).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse

from . import azure_tts, youtube_ingest
from .render import get_duration
from .tts import KNOWN_VOICES as PIPER_KNOWN_VOICES
from .tts import synthesize_to_wav

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
LIBRARY_DIR = MEDIA_DIR / "library"
OUTPUT_DIR = MEDIA_DIR / "outputs"
MUSIC_DIR = MEDIA_DIR / "music"
# Downloaded photos (keyed by URL hash), shared across projects like the library.
IMAGE_CACHE_DIR = MEDIA_DIR / "script_images"
SV_DIR = BASE_DIR / "workspace" / "script_video"
BRIEF_PATH = SV_DIR / "brief.md"
SHOTS_PATH = SV_DIR / "shots.md"
SHEETS_DIR = SV_DIR / "sheets"
THUMBS_DIR = SV_DIR / "thumbs"
VOICE_DIR = SV_DIR / "voice"
SEGMENTS_DIR = SV_DIR / "segments"

USER_AGENT = "VideoEditorY/1.0 (personal video editing app)"
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
WIDTH, HEIGHT, FPS = 1920, 1080, 30
VOICE_DELAY = 0.15      # silence before a scene's voice-over starts
SCENE_TAIL = 0.5        # silence after it, before the next scene
DEFAULT_IMAGE_SECONDS = 3.0
# Video clips are short and lively: at most MAX_CLIP_SECONDS each, and the
# footage should add up to about FOOTAGE_SHARE of the video (30 s in 3 min).
MAX_CLIP_SECONDS = 4.5
MIN_CLIP_SECONDS = 1.0
MIN_IMAGE_SECONDS = 1.5
FOOTAGE_SHARE = 1 / 6
WORDS_PER_SECOND = 2.3
# The "look" of every video clip (can be turned off in the app): a fixed
# 10% zoom for the clip's whole length, a little more saturation and
# contrast, a touch of warmth, light sharpening and a soft vignette.
CLIP_ZOOM = 1.10
CLIP_LOOK = ",".join([
    "eq=saturation=1.15:contrast=1.06:brightness=0.01",
    "colorbalance=rs=0.03:gs=0.01:bs=-0.03",
    "unsharp=5:5:0.35",
    "vignette=angle=PI/6",
])
TITLE_SECONDS = 2.5
MUSIC_FADE_OUT = 2.0
# `crop`: keep the top 85% (centred), which drops a broadcast lower third.
CROP_FILTER = "crop=iw*0.852:ih*0.852:(iw-ow)/2:0"
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
LANGUAGES = ("Russian", "English")
SCRIPT_SOURCES = ("research", "resources", "own")

router = APIRouter(prefix="/api/script-video")


# --- shots.md ---------------------------------------------------------------


@dataclass
class Shot:
    kind: str                     # "video" | "image"
    url: str
    start: float | None = None    # video: range in the source
    end: float | None = None
    seconds: float | None = None  # image: how long it's shown
    crop: bool = False
    caption: str = ""
    title: str = ""
    zoom: str = "in"
    # Filled in by the app (not written back to shots.md):
    key: str = ""                 # media cache key
    status: str = "pending"       # pending | ready | error
    error: str = ""

    @property
    def length(self) -> float:
        """How long the shot plays before fitting (a clip at most MAX_CLIP_SECONDS)."""
        if self.kind == "video" and self.start is not None and self.end is not None:
            return min(MAX_CLIP_SECONDS, max(0.0, self.end - self.start))
        return self.seconds or DEFAULT_IMAGE_SECONDS


@dataclass
class Scene:
    title: str
    text: str
    shots: list[Shot] = field(default_factory=list)


@dataclass
class Plan:
    title: str = ""
    scenes: list[Scene] = field(default_factory=list)
    credits: list[str] = field(default_factory=list)


_SCENE_RE = re.compile(r"^##\s+Scene\s+\d+\s*(?:\|\s*(.*))?$", re.IGNORECASE)
_TIME_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)$|^(\d+(?:[.,]\d+)?)$")


def parse_time(text: str) -> float:
    """`1:02:03.5`, `2:03.5`, `123.5` -> seconds."""
    text = text.strip()
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError(f"Not a time: {text!r}")
    if match.group(4) is not None:
        return float(match.group(4).replace(",", "."))
    hours = int(match.group(1) or 0)
    return hours * 3600 + int(match.group(2)) * 60 + float(match.group(3).replace(",", "."))


def format_time(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    body = f"{minutes}:{secs:04.1f}"
    return f"{hours}:{minutes:02d}:{secs:04.1f}" if hours else body


def _parse_shot(line: str) -> Shot:
    parts = [p.strip() for p in line.lstrip("-* ").split("|")]
    if len(parts) < 2:
        raise ValueError("needs at least `kind | link`")
    kind = parts[0].lower()
    if kind not in ("video", "image"):
        raise ValueError(f"kind must be video or image, not {parts[0]!r}")
    shot = Shot(kind=kind, url=parts[1])
    options = parts[2:]
    if options and kind == "video":
        timing = options.pop(0)
        if "-" not in timing.replace(" - ", "-"):
            raise ValueError(f"video needs a time range like 0:50-0:53, got {timing!r}")
        start_text, end_text = re.split(r"\s*[-–]\s*", timing, maxsplit=1)
        shot.start, shot.end = parse_time(start_text), parse_time(end_text)
        if shot.end <= shot.start:
            raise ValueError(f"the range ends before it starts: {timing!r}")
    elif kind == "video":
        raise ValueError("video needs a time range like 0:50-0:53")
    elif options and re.fullmatch(r"\d+(?:[.,]\d+)?\s*s?", options[0]):
        shot.seconds = float(options.pop(0).rstrip("s ").replace(",", "."))
    for option in options:
        name, _, value = option.partition(":")
        name = name.strip().lower()
        if name == "crop":
            shot.crop = True
        elif name == "caption":
            shot.caption = value.strip()
        elif name == "title":
            shot.title = value.strip()
        elif name == "zoom":
            shot.zoom = "out" if value.strip().lower() == "out" else "in"
        elif option:
            raise ValueError(f"unknown option {option!r}")
    return shot


def parse_shots(text: str) -> tuple[Plan, list[str]]:
    """Returns the plan and human-readable problems (line numbers 1-based)."""
    plan = Plan()
    problems: list[str] = []
    scene: Scene | None = None
    section = "intro"
    body: list[str] = []

    def flush_body() -> None:
        if scene is not None and body:
            scene.text = (scene.text + "\n\n" if scene.text else "") + " ".join(body).strip()
            body.clear()

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("# ") and not plan.title:
            plan.title = line[2:].strip()
            continue
        scene_match = _SCENE_RE.match(line)
        if scene_match:
            flush_body()
            scene = Scene(title=(scene_match.group(1) or "").strip(), text="")
            plan.scenes.append(scene)
            section = "scene"
            continue
        if line.startswith("## "):
            flush_body()
            scene = None
            section = line[3:].strip().upper()
            continue
        if section == "CREDITS":
            if line:
                plan.credits.append(line.lstrip("-* ").strip())
            continue
        if section != "scene" or scene is None:
            continue
        if not line:
            flush_body()
            continue
        if line.startswith(("- ", "* ")) and "|" in line:
            flush_body()
            try:
                scene.shots.append(_parse_shot(line))
            except ValueError as exc:
                problems.append(f"Line {number}: {exc}")
            continue
        body.append(line)
    flush_body()

    for index, s in enumerate(plan.scenes, 1):
        if not s.text.strip():
            problems.append(f"Scene {index} has no text to read aloud.")
        if not s.shots:
            problems.append(f"Scene {index} has no shots.")
    if not plan.scenes:
        problems.append("No scenes found — each one starts with `## Scene N | Name`.")
    return plan, problems


def format_shots(plan: Plan) -> str:
    """Writes the plan back in shots.md format (after edits in the app)."""
    lines = [f"# {plan.title or 'Untitled video'}", ""]
    for index, scene in enumerate(plan.scenes, 1):
        lines.append(f"## Scene {index} | {scene.title}".rstrip(" |"))
        lines += [scene.text.strip(), ""]
        for shot in scene.shots:
            parts = [shot.kind, shot.url]
            if shot.kind == "video":
                parts.append(f"{format_time(shot.start or 0)}-{format_time(shot.end or 0)}")
            elif shot.seconds:
                parts.append(f"{shot.seconds:g}")
            if shot.crop:
                parts.append("crop")
            if shot.caption:
                parts.append(f"caption: {shot.caption}")
            if shot.title:
                parts.append(f"title: {shot.title}")
            if shot.kind == "image" and shot.zoom == "out":
                parts.append("zoom: out")
            lines.append("- " + " | ".join(parts))
        lines.append("")
    if plan.credits:
        lines += ["## CREDITS"] + [f"- {c}" for c in plan.credits] + [""]
    return "\n".join(lines)


def plan_from_json(data: dict) -> Plan:
    plan = Plan(title=data.get("title", ""), credits=list(data.get("credits", [])))
    for s in data.get("scenes", []):
        scene = Scene(title=s.get("title", ""), text=s.get("text", ""))
        for raw in s.get("shots", []):
            shot = Shot(kind=raw["kind"], url=raw["url"])
            for name in ("start", "end", "seconds"):
                if raw.get(name) not in (None, ""):
                    setattr(shot, name, float(raw[name]))
            shot.crop = bool(raw.get("crop"))
            shot.caption = raw.get("caption", "") or ""
            shot.title = raw.get("title", "") or ""
            shot.zoom = raw.get("zoom", "in") or "in"
            scene.shots.append(shot)
        plan.scenes.append(scene)
    return plan


# --- media: videos (library cache) and images ------------------------------


def _video_cache_dir(url: str) -> Path:
    video_id = youtube_ingest.video_id_from_url(url)
    key = video_id or "url_" + hashlib.sha1(url.encode()).hexdigest()[:16]
    return LIBRARY_DIR / key


def cached_video(url: str) -> Path | None:
    folder = _video_cache_dir(url)
    found = sorted(folder.glob("video.*")) if folder.exists() else []
    return found[0] if found else None


def _image_cache_path(url: str) -> Path | None:
    stem = hashlib.sha1(url.encode()).hexdigest()[:16]
    found = sorted(IMAGE_CACHE_DIR.glob(stem + ".*")) if IMAGE_CACHE_DIR.exists() else []
    return found[0] if found else None


def _http_get(url: str, timeout: float = 60) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


_COMMONS_FILE_RE = re.compile(r"(?:commons|[a-z]{2,3})\.(?:m\.)?wikipedia\.org/wiki/(File:[^?#]+)|commons\.wikimedia\.org/wiki/(File:[^?#]+)")


def _resolve_image_url(url: str) -> str:
    """A Wikimedia Commons / Wikipedia `File:` page -> a 2000px-wide image URL.
    Any other link is used as it is (it has to point at the image itself)."""
    match = _COMMONS_FILE_RE.search(url)
    if not match:
        return url
    title = urllib.parse.unquote(match.group(1) or match.group(2))
    api = (
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
        "&iiprop=url&iiurlwidth=2000&titles=" + urllib.parse.quote(title)
    )
    data = json.loads(_http_get(api)[0])
    page = next(iter(data["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise RuntimeError(f"Wikimedia has no file named {title}")
    info = page["imageinfo"][0]
    return info.get("thumburl") or info["url"]


def download_image(url: str) -> Path:
    cached = _image_cache_path(url)
    if cached:
        return cached
    data, content_type = _http_get(_resolve_image_url(url))
    looks_like_image = re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.IGNORECASE)
    if not content_type.startswith("image/") and not looks_like_image:
        raise RuntimeError("The link doesn't point at an image (use the image file itself, or a Wikimedia File: page).")
    suffix = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type.split(";")[0], ".jpg")
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest()[:16] + suffix)
    path.write_bytes(data)
    return path


def download_video(url: str, on_progress) -> Path:
    cached = cached_video(url)
    if cached:
        return cached
    target = _video_cache_dir(url)
    scratch = target.parent / f"_download_{target.name}"
    shutil.rmtree(scratch, ignore_errors=True)
    downloaded = youtube_ingest.download_video(url, scratch, on_progress)
    target.mkdir(parents=True, exist_ok=True)
    final = target / f"video{downloaded.suffix}"
    downloaded.replace(final)
    shutil.rmtree(scratch, ignore_errors=True)
    return final


def media_path(shot: Shot) -> Path | None:
    return cached_video(shot.url) if shot.kind == "video" else _image_cache_path(shot.url)


def shot_key(shot: Shot) -> str:
    return hashlib.sha1(f"{shot.kind}|{shot.url}".encode()).hexdigest()[:12]


# --- contact sheets for Claude and thumbnails for the app ------------------

SHEET_COLUMNS, SHEET_ROWS = 6, 8
SHEET_MAX_PAGES = 8


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


def make_contact_sheets(video: Path, label: str) -> list[dict]:
    """Timestamped frame grids of a whole video (6x8 frames per page)."""
    duration = get_duration(str(video))
    per_page = SHEET_COLUMNS * SHEET_ROWS
    interval = max(2.0, math.ceil(duration / (per_page * SHEET_MAX_PAGES)))
    pages = max(1, math.ceil(duration / (interval * per_page)))
    sheets = []
    for page in range(pages):
        start = page * per_page * interval
        out = SHEETS_DIR / f"{label}_p{page + 1}.jpg"
        _ffmpeg([
            "-ss", f"{start}", "-t", f"{per_page * interval}", "-i", str(video),
            "-vf", (
                f"fps=1/{interval},scale=480:-2,"
                f"drawtext=text='%{{pts\\:hms\\:{start}}}':x=6:y=6:fontsize=26:fontcolor=yellow:box=1:boxcolor=black@0.8,"
                f"tile={SHEET_COLUMNS}x{SHEET_ROWS}"
            ),
            "-frames:v", "1", "-q:v", "4", str(out),
        ])
        sheets.append({
            "file": out.name, "from": format_time(start),
            "to": format_time(min(duration, start + per_page * interval)), "every": interval,
        })
    return sheets


def make_thumbnail(shot: Shot, path: Path) -> None:
    out = THUMBS_DIR / f"{shot.key}_{shot.start or 0:.1f}.jpg"
    if out.exists():
        return
    if shot.kind == "video":
        at = ((shot.start or 0) + (shot.end or 0)) / 2
        _ffmpeg(["-ss", f"{at}", "-i", str(path), "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", str(out)])
    else:
        _ffmpeg(["-i", str(path), "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", str(out)])


def thumbnail_name(shot: Shot) -> str:
    return f"{shot.key}_{shot.start or 0:.1f}.jpg"


# --- rendering --------------------------------------------------------------


def _font() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return ""


def _text_file(text: str) -> str:
    """drawtext reads captions from a file: no escaping of quotes, colons,
    commas or % to get wrong (expansion is off too)."""
    SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SEGMENTS_DIR / ("text_" + hashlib.sha1(text.encode()).hexdigest()[:12] + ".txt")
    path.write_text(text, encoding="utf-8")
    return path.as_posix()


def _font_arg(font: str) -> str:
    return f"fontfile='{font}':" if font else ""


def _caption_filter(text: str, font: str) -> str:
    size = 54 if len(text) <= 32 else 46
    return (f"drawtext={_font_arg(font)}textfile='{_text_file(text)}':expansion=none:fontsize={size}:"
            f"fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=18:x=(w-tw)/2:y=h-170")


def _title_filter(text: str, font: str, length: float) -> str:
    return (f"drawtext={_font_arg(font)}textfile='{_text_file(text)}':expansion=none:fontsize=72:"
            f"fontcolor=white:box=1:boxcolor=0xC8102E@0.9:boxborderw=22:x=60:y=60:"
            f"enable='lt(t,{min(TITLE_SECONDS, length):.2f})'")


def _overlays(shot: Shot, font: str, length: float) -> list[str]:
    filters = []
    if shot.caption:
        filters.append(_caption_filter(shot.caption, font))
    if shot.title:
        filters.append(_title_filter(shot.title, font, length))
    return filters


def _render_video_shot(
    shot: Shot, source: Path, length: float, out: Path, font: str, effects: bool = True,
) -> None:
    """`length` seconds of the source from the shot's start (it plays on
    past the range's end if the scene needs it; the source's own end holds
    its last frame). With `effects`, the CLIP_ZOOM zoom and CLIP_LOOK."""
    duration = get_duration(str(source))
    start = min(max(0.0, shot.start or 0.0), max(0.0, duration - 0.5))
    available = max(0.1, min(duration - start, length))
    vf = [CROP_FILTER] if shot.crop else []
    if effects:
        # Static zoom: the centre 1/CLIP_ZOOM of the frame, scaled back up.
        vf.append(f"crop=iw/{CLIP_ZOOM}:ih/{CLIP_ZOOM}:(iw-ow)/2:(ih-oh)/2")
    vf += [
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
        f"fps={FPS}", "setsar=1",
        f"tpad=stop_mode=clone:stop_duration={length:.3f}",
        f"trim=duration={length:.3f}",
    ]
    if effects:
        vf.append(CLIP_LOOK)
    vf += _overlays(shot, font, length)
    _ffmpeg(["-ss", f"{start:.3f}", "-t", f"{available:.3f}", "-i", str(source), "-an",
             "-vf", ",".join(vf), "-frames:v", str(round(length * FPS)), *ENCODE, str(out)])


def _render_image_shot(shot: Shot, source: Path, length: float, out: Path, font: str) -> None:
    """The whole photo over a blurred copy of itself, slowly zooming."""
    frames = max(1, round(length * FPS))
    if shot.zoom == "out":
        zoom = f"max(1.10-0.10*on/{frames},1)"
    else:
        zoom = f"min(1+0.10*on/{frames},1.10)"
    graph = (
        f"[0]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
        f"boxblur=30:3,eq=brightness=-0.15[bg];"
        f"[0]scale={WIDTH - 40}:{HEIGHT - 40}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={WIDTH * 2}:{HEIGHT * 2},"
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        + ",".join(["setsar=1", *_overlays(shot, font, length)]) + "[v]"
    )
    _ffmpeg(["-loop", "1", "-i", str(source), "-filter_complex", graph, "-map", "[v]",
             "-frames:v", str(frames), *ENCODE, str(out)])


def fit_lengths(shots: list[Shot], total: float) -> list[float]:
    """Shot lengths that add up to `total` (the scene's voice-over).

    Clips keep their own length (at most MAX_CLIP_SECONDS); photos take up
    the slack, shared evenly. A scene without photos lengthens its clips
    evenly up to MAX_CLIP_SECONDS, then the last one plays on. When the
    shots are too long, photos shrink first, then clips from the end."""
    lengths = [s.length for s in shots]
    images = [i for i, s in enumerate(shots) if s.kind == "image"]
    videos = [i for i, s in enumerate(shots) if s.kind == "video"]
    slack = total - sum(lengths)
    if slack > 0:
        if images:
            for i in images:
                lengths[i] += slack / len(images)
            return lengths
        while slack > 1e-6:
            growable = [i for i in videos if lengths[i] < MAX_CLIP_SECONDS - 1e-6]
            if not growable:
                lengths[videos[-1]] += slack
                break
            share = slack / len(growable)
            for i in growable:
                grow = min(share, MAX_CLIP_SECONDS - lengths[i])
                lengths[i] += grow
                slack -= grow
        return lengths
    excess = -slack
    for indices, floor in ((images, MIN_IMAGE_SECONDS), (videos, MIN_CLIP_SECONDS)):
        for i in reversed(indices):
            if excess <= 1e-6:
                return lengths
            cut = min(excess, max(0.0, lengths[i] - floor))
            lengths[i] -= cut
            excess -= cut
    if excess > 1e-6:  # Every shot is at its minimum: drop the rest evenly.
        lengths = [max(0.3, length - excess / len(lengths)) for length in lengths]
    return lengths


def estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_SECOND + VOICE_DELAY + SCENE_TAIL


def footage_stats(plan: Plan) -> dict:
    """Rough totals for the app: how long the video will be, how much of it
    is video footage, and how much footage FOOTAGE_SHARE asks for."""
    total = sum(estimate_seconds(scene.text) for scene in plan.scenes)
    footage = sum(s.length for scene in plan.scenes for s in scene.shots if s.kind == "video")
    clips = sum(1 for scene in plan.scenes for s in scene.shots if s.kind == "video")
    return {"total": round(total, 1), "footage": round(footage, 1), "clips": clips,
            "target": round(total * FOOTAGE_SHARE, 1)}


def synthesize(text: str, voice: str, base: Path) -> Path:
    if voice in PIPER_KNOWN_VOICES:
        path = base.with_suffix(".wav")
        synthesize_to_wav(text, voice, str(path))
    elif voice in azure_tts.KNOWN_VOICES:
        path = base.with_suffix(".mp3")
        azure_tts.synthesize_to_file(text, voice, str(path))
    else:
        raise ValueError(f"Unknown voice: {voice}")
    return path


# --- background jobs ----------------------------------------------------------

JOB: dict = {"status": "idle", "message": "", "progress": 0.0, "error": None, "output": None, "credits": None}
_JOB_LOCK = threading.Lock()


def _set(status: str | None = None, message: str | None = None, progress: float | None = None) -> None:
    if status is not None:
        JOB["status"] = status
    if message is not None:
        JOB["message"] = message
    if progress is not None:
        JOB["progress"] = progress


def _start_job(target, *args) -> None:
    with _JOB_LOCK:
        if JOB["status"] in ("fetching", "voicing", "rendering"):
            raise HTTPException(409, "Something is already running — wait for it to finish.")
        JOB.update(status="starting", message="", progress=0.0, error=None)

    def run() -> None:
        try:
            target(*args)
        except Exception as exc:  # shown in the app
            JOB.update(status="error", error=str(exc))

    threading.Thread(target=run, daemon=True).start()


def _load_plan() -> Plan:
    if not SHOTS_PATH.exists():
        raise HTTPException(404, "No workspace/script_video/shots.md yet — ask Claude for it first (Mode 6).")
    plan, problems = parse_shots(SHOTS_PATH.read_text(encoding="utf-8"))
    if not plan.scenes:
        raise HTTPException(400, "; ".join(problems))
    return plan


def _fetch_all(plan: Plan) -> None:
    shots = [s for scene in plan.scenes for s in scene.shots]
    unique: dict[tuple[str, str], Shot] = {}
    for shot in shots:
        unique.setdefault((shot.kind, shot.url), shot)
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    for position, ((kind, url), shot) in enumerate(unique.items()):
        base = position / max(1, len(unique))
        label = f"{position + 1}/{len(unique)}"
        _set("fetching", f"Downloading {label}…", base)
        try:
            if kind == "video":
                def progress(frac: float, message: str) -> None:
                    _set(message=f"Downloading video {label}… {frac * 100:.0f}%", progress=base + frac / len(unique))
                download_video(url, progress)
            else:
                download_image(url)
        except Exception as exc:
            failures.append(f"{url}: {exc}")
    _set(message="Making contact sheets for Claude…")
    _write_sheets(plan)
    _write_thumbnails(plan)
    JOB.update(status="fetched", progress=1.0,
               message=("Some links failed: " + " · ".join(failures)) if failures else "")


def _write_sheets(plan: Plan) -> None:
    """sheets/README.md lists, per video, its link and its sheets — Claude
    reads this in the "check the footage" pass."""
    for old in SHEETS_DIR.glob("*"):
        old.unlink()
    lines = [
        "# Contact sheets",
        "",
        "Each video the shots use, as grids of frames with their time in the video",
        "(yellow, top-left). Use them to check and fix the time ranges in shots.md.",
        "",
    ]
    seen = set()
    number = 0
    for scene in plan.scenes:
        for shot in scene.shots:
            video = cached_video(shot.url) if shot.kind == "video" else None
            # The same video can be linked in different forms (youtu.be/…).
            if not video or video in seen:
                continue
            seen.add(video)
            number += 1
            sheets = make_contact_sheets(video, f"video{number}")
            lines += [f"## video{number} — {shot.url}", f"Length {format_time(get_duration(str(video)))}", ""]
            lines += [f"- {s['file']}: {s['from']} – {s['to']}, a frame every {s['every']:g} s" for s in sheets]
            lines.append("")
    (SHEETS_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_thumbnails(plan: Plan) -> None:
    for scene in plan.scenes:
        for shot in scene.shots:
            shot.key = shot_key(shot)
            path = media_path(shot)
            if path:
                try:
                    make_thumbnail(shot, path)
                except subprocess.CalledProcessError:
                    pass


def _render(plan: Plan, voice: str, music: str, music_db: float, effects: bool = True) -> None:
    font = _font()
    for folder in (VOICE_DIR, SEGMENTS_DIR):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    missing = [s.url for sc in plan.scenes for s in sc.shots if not media_path(s)]
    if missing:
        raise RuntimeError("Not downloaded yet: " + ", ".join(dict.fromkeys(missing)) + " — press Download footage first.")

    total = len(plan.scenes)
    voices = []
    for index, scene in enumerate(plan.scenes):
        _set("voicing", f"Voicing scene {index + 1}/{total}…", index / total * 0.3)
        voices.append(synthesize(scene.text, voice, VOICE_DIR / f"scene{index:03d}"))

    scene_files = []
    for index, (scene, audio) in enumerate(zip(plan.scenes, voices)):
        _set("rendering", f"Rendering scene {index + 1}/{total}…", 0.3 + index / total * 0.65)
        length = round(get_duration(str(audio)) + VOICE_DELAY + SCENE_TAIL, 3)
        parts = []
        for number, (shot, shot_length) in enumerate(zip(scene.shots, fit_lengths(scene.shots, length))):
            out = SEGMENTS_DIR / f"s{index:03d}_{number:02d}.mp4"
            source = media_path(shot)
            if shot.kind == "video":
                _render_video_shot(shot, source, shot_length, out, font, effects)
            else:
                _render_image_shot(shot, source, shot_length, out, font)
            parts.append(out)
        listing = SEGMENTS_DIR / f"s{index:03d}.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        scene_out = SEGMENTS_DIR / f"scene{index:03d}.mp4"
        delay = round(VOICE_DELAY * 1000)
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio),
                 "-filter_complex", f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={delay}|{delay},apad[a]",
                 "-map", "0:v", "-map", "[a]", "-t", f"{length}", *ENCODE, "-c:a", "aac", "-b:a", "192k", str(scene_out)])
        scene_files.append(scene_out)

    _set("rendering", "Joining scenes…", 0.96)
    listing = SEGMENTS_DIR / "all.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in scene_files), encoding="utf-8")
    joined = SEGMENTS_DIR / "joined.mp4"
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)])

    stamp = time.strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"script_video_{stamp}.mp4"
    duration = get_duration(str(joined))
    if music:
        music_path = MUSIC_DIR / Path(music).name
        graph = (
            f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={music_db}dB,"
            f"afade=t=out:st={max(0.0, duration - MUSIC_FADE_OUT):.3f}:d={MUSIC_FADE_OUT}[m];"
            f"[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        )
        _ffmpeg(["-i", str(joined), "-stream_loop", "-1", "-i", str(music_path), "-filter_complex", graph,
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{duration:.3f}", "-movflags", "+faststart", str(output)])
    else:
        _ffmpeg(["-i", str(joined), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)])

    credits = output.with_name(output.stem + "_credits.txt")
    credits.write_text(_credits_text(plan, voice), encoding="utf-8")
    shutil.rmtree(SEGMENTS_DIR, ignore_errors=True)
    JOB.update(status="done", progress=1.0, message="", output=output.name, credits=credits.name)


def _credits_text(plan: Plan, voice: str) -> str:
    lines = [plan.title or "Video", "", f"Voice: {voice}", "", "Footage and photos:"]
    lines += [f"- {url}" for url in dict.fromkeys(s.url for sc in plan.scenes for s in sc.shots)]
    if plan.credits:
        lines += ["", "Credits:"] + [f"- {c}" for c in plan.credits]
    return "\n".join(lines) + "\n"


# --- API ----------------------------------------------------------------------


def _public_plan(plan: Plan, problems: list[str]) -> dict:
    scenes = []
    for scene in plan.scenes:
        shots = []
        for shot in scene.shots:
            shot.key = shot_key(shot)
            path = media_path(shot)
            thumb = THUMBS_DIR / thumbnail_name(shot)
            if path and not thumb.exists():
                try:
                    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
                    make_thumbnail(shot, path)
                except subprocess.CalledProcessError:
                    pass
            data = asdict(shot)
            data["status"] = "ready" if path else "pending"
            data["length"] = round(shot.length, 2)
            data["thumb"] = thumbnail_name(shot) if thumb.exists() else None
            shots.append(data)
        scenes.append({"title": scene.title, "text": scene.text, "shots": shots})
    return {"title": plan.title, "credits": plan.credits, "scenes": scenes, "problems": problems,
            "has_sheets": (SHEETS_DIR / "README.md").exists(), "stats": footage_stats(plan),
            "max_clip": MAX_CLIP_SECONDS}


@router.post("/brief")
def save_brief(
    source: str = Form(...),
    topic: str = Form(""),
    material: str = Form(""),
    language: str = Form("Russian"),
    minutes: float = Form(3.0),
):
    """Step 1 of a script video: what Claude should make (brief.md)."""
    if source not in SCRIPT_SOURCES:
        raise HTTPException(400, f"Unknown script source: {source}")
    if language not in LANGUAGES:
        raise HTTPException(400, f"Unknown language: {language}")
    if not topic.strip() and not material.strip():
        raise HTTPException(400, "Write what the video is about (or paste your script / resources).")
    if source in ("resources", "own") and not material.strip():
        raise HTTPException(400, "Paste your resources or your script first.")
    source_text = {
        "research": "Claude researches the topic itself and writes the script.",
        "resources": "Claude writes the script from the resources below (and may check facts online).",
        "own": "The script below is the user's own: keep its wording, only split it into scenes and find the visuals.",
    }[source]
    lines = [
        "# Script video brief",
        "",
        f"- Script: {source} — {source_text}",
        f"- Language of the voice-over: {language}",
        f"- Target length: about {minutes:g} minutes",
        "- Format: 16:9, 1920x1080",
        "",
        "## Topic / instruction",
        "",
        topic.strip() or "(none — see the material below)",
        "",
    ]
    if material.strip():
        lines += ["## " + ("Script" if source == "own" else "Resources"), "", material.strip(), ""]
    SV_DIR.mkdir(parents=True, exist_ok=True)
    BRIEF_PATH.write_text("\n".join(lines), encoding="utf-8")
    return {"saved": True}


@router.get("/brief")
def get_brief():
    return {"exists": BRIEF_PATH.exists(), "text": BRIEF_PATH.read_text(encoding="utf-8") if BRIEF_PATH.exists() else ""}


@router.get("/shots")
def get_shots():
    plan = _load_plan()
    _, problems = parse_shots(SHOTS_PATH.read_text(encoding="utf-8"))
    return _public_plan(plan, problems)


@router.post("/shots")
def save_shots(plan_json: str = Form(...)):
    """Edits made in the app, written back to shots.md."""
    try:
        plan = plan_from_json(json.loads(plan_json))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, f"Invalid plan: {exc}")
    text = format_shots(plan)
    reparsed, problems = parse_shots(text)
    SHOTS_PATH.write_text(text, encoding="utf-8")
    return _public_plan(reparsed, problems)


@router.post("/fetch")
def fetch():
    plan = _load_plan()
    _start_job(_fetch_all, plan)
    return {"status": "started"}


@router.post("/render")
def render(
    voice: str = Form(...), music: str = Form(""), music_db: float = Form(-24.0), clip_effects: bool = Form(True),
):
    if voice not in PIPER_KNOWN_VOICES and voice not in azure_tts.KNOWN_VOICES:
        raise HTTPException(400, f"Unknown voice: {voice}")
    if music and not (MUSIC_DIR / Path(music).name).is_file():
        raise HTTPException(404, f"No saved music track named {music!r}.")
    plan = _load_plan()
    JOB.update(output=None, credits=None)
    _start_job(_render, plan, voice, music, music_db, clip_effects)
    return {"status": "started"}


@router.get("/status")
def status():
    data = dict(JOB)
    if data.get("output"):
        data["download_url"] = f"/api/download/{data['output']}"
        data["credits_url"] = f"/api/script-video/credits/{data['credits']}"
    return data


@router.get("/thumb/{name}")
def thumb(name: str):
    path = THUMBS_DIR / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "No such thumbnail.")
    return FileResponse(path)


@router.get("/credits/{name}")
def credits(name: str):
    path = OUTPUT_DIR / Path(name).name
    if not path.is_file() or not path.name.endswith("_credits.txt"):
        raise HTTPException(404, "No such credits file.")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=path.name)
