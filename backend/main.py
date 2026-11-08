"""FastAPI backend for VideoEditorY.

Single local process that serves both the API and the static frontend, so
the whole app is launched with one command on Windows or Linux (see
run.py). State is kept in memory since this is a single-user local tool.
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import azure_tts, broll, duration_fit, youtube_ingest
from .additions import build_script, merge_additions, parse_additions
from .chunker import TextChunk, chunk_by_outline, chunk_kept_cues, kept_cues
from .editor import Cut, build_timeline, calculate_keep_segments, normalize_cuts, output_time
from .parser import ParsedResponse, parse_ai_response, parse_outline, parse_vtt
from .render import FFmpegNotFoundError, get_duration, render_video, render_video_with_audio
from .tts import KNOWN_VOICES as PIPER_KNOWN_VOICES
from .tts import VoiceNotAvailableError, list_available_voices, synthesize_to_wav

# Piper voice that predicts Azure durations (calibrated to Azure's pace).
ESTIMATOR_PIPER_VOICE = "ru_RU-denis-medium"

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
UPLOAD_DIR = MEDIA_DIR / "uploads"
OUTPUT_DIR = MEDIA_DIR / "outputs"
# Downloaded videos + Whisper transcripts, keyed by YouTube video ID, so
# pasting the same video again skips the download and transcription.
# Layout: library/<video_id>/video.<ext> and library/<video_id>/<language>_<model>.vtt
LIBRARY_DIR = MEDIA_DIR / "library"
FRONTEND_DIR = BASE_DIR / "frontend"

# Fixed, predictable location mirroring the current video+VTT — so Claude
# Desktop/Claude Code can be pointed at the same path every time, regardless
# of which internal project_id is active. Holds exactly one project at a
# time (single-user tool); a new YouTube ingest overwrites whatever was here.
WORKSPACE_DIR = BASE_DIR / "workspace"
OUTLINE_PATH = WORKSPACE_DIR / "outline.md"
CUTS_PATH = WORKSPACE_DIR / "cuts.md"
# Mode 4 (new parts): the app writes the kept text to script.md, Claude
# answers with additions.md (see backend/additions.py).
SCRIPT_PATH = WORKSPACE_DIR / "script.md"
ADDITIONS_PATH = WORKSPACE_DIR / "additions.md"
CHUNK_AUDIO_DIR = WORKSPACE_DIR / "chunk_audio"

# Silence around an added part's voice-over (each side), so it doesn't butt
# straight against the original speech.
INSERT_PAD_SECONDS = 0.3

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VideoEditorY")

# project_id -> {video_path, duration, status, phase, phase_message,
#                progress, output_path, error, vtt_text, source_url, language}
PROJECTS: dict[str, dict] = {}


def _get_project(project_id: str) -> dict:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(404, "Unknown project_id — paste a YouTube URL first.")
    return project


def _mirror_into_workspace(video_path: Path, vtt_text: str) -> None:
    """Mirrors the current project's video + transcript into the fixed
    workspace/ folder so Claude Desktop/Claude Code always has a stable
    path to work with. This is a new "current project" — drop any previous
    video file (could have a different extension) and any stale outline/cuts
    output from whatever was there before."""

    for old_video in WORKSPACE_DIR.glob("video.*"):
        old_video.unlink()
    shutil.copyfile(video_path, WORKSPACE_DIR / f"video{video_path.suffix}")
    (WORKSPACE_DIR / "subtitles.vtt").write_text(vtt_text, encoding="utf-8")
    OUTLINE_PATH.unlink(missing_ok=True)
    CUTS_PATH.unlink(missing_ok=True)
    SCRIPT_PATH.unlink(missing_ok=True)
    ADDITIONS_PATH.unlink(missing_ok=True)
    shutil.rmtree(CHUNK_AUDIO_DIR, ignore_errors=True)


# --- YouTube ingestion (download + Whisper transcription) -----------------


def _run_ingest(project_id: str, youtube_url: str, language: str) -> None:
    project = PROJECTS[project_id]
    project_dir = UPLOAD_DIR / project_id

    def set_phase(phase: str, message: str, progress: float = 0.0) -> None:
        project["status"] = "processing"
        project["phase"] = phase
        project["phase_message"] = message
        project["progress"] = progress

    video_id = youtube_ingest.video_id_from_url(youtube_url)
    # Unrecognized URLs still work, they just don't get cached.
    library_dir = LIBRARY_DIR / video_id if video_id else project_dir
    transcript_cache = library_dir / f"{language}_{youtube_ingest.DEFAULT_WHISPER_MODEL}.vtt"

    try:
        cached_videos = sorted(library_dir.glob("video.*")) if video_id else []
        if cached_videos:
            video_path = cached_videos[0]
            project["video_cached"] = True
        else:
            set_phase("downloading", "Downloading…", 0.0)
            video_path = youtube_ingest.download_video(
                youtube_url, project_dir, on_progress=lambda frac, msg: set_phase("downloading", msg, frac)
            )
            # Only a finished download enters the library — a failed one can
            # leave yt-dlp's .part/format files behind, which must not look cached.
            if video_id:
                library_dir.mkdir(parents=True, exist_ok=True)
                video_path = Path(shutil.move(str(video_path), library_dir / f"video{video_path.suffix}"))

        duration = get_duration(str(video_path))
        project["video_path"] = str(video_path)
        project["duration"] = duration

        if video_id and transcript_cache.exists():
            vtt_text = transcript_cache.read_text(encoding="utf-8")
            project["transcript_cached"] = True
        else:
            set_phase("extracting_audio", "Extracting audio for transcription…", 0.0)
            audio_path = youtube_ingest.extract_audio(video_path, project_dir)

            vtt_text = youtube_ingest.transcribe(
                audio_path,
                language=language,
                on_progress=lambda frac, msg: set_phase("transcribing", msg, frac),
            )
            if video_id:
                transcript_cache.write_text(vtt_text, encoding="utf-8")

        project["vtt_text"] = vtt_text
        (project_dir / "subtitles.vtt").write_text(vtt_text, encoding="utf-8")

        _mirror_into_workspace(video_path, vtt_text)

        project["status"] = "done"
        project["phase"] = "done"
        project["progress"] = 1.0

    except youtube_ingest.DownloadError as exc:
        project["status"] = "error"
        project["phase"] = "downloading"
        project["error"] = str(exc)
    except youtube_ingest.TranscriptionError as exc:
        project["status"] = "error"
        project["phase"] = "transcribing"
        project["error"] = str(exc)
    except FFmpegNotFoundError as exc:
        project["status"] = "error"
        project["error"] = str(exc)
    except Exception as exc:
        project["status"] = "error"
        project["error"] = f"Unexpected error: {exc}"


@app.post("/api/ingest")
async def ingest_youtube(youtube_url: str = Form(...), language: str = Form(...)):
    project_id = str(uuid.uuid4())
    project_dir = UPLOAD_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    PROJECTS[project_id] = {
        "status": "processing",
        "phase": "queued",
        "phase_message": "Queued…",
        "progress": 0.0,
        "video_path": None,
        "duration": None,
        "output_path": None,
        "error": None,
        "vtt_text": None,
        "source_url": youtube_url,
        "language": language,
    }

    thread = threading.Thread(
        target=_run_ingest, args=(project_id, youtube_url, language), daemon=True
    )
    thread.start()

    return {"project_id": project_id}


@app.get("/api/project/{project_id}/transcript")
async def get_transcript(project_id: str):
    project = _get_project(project_id)
    if not project.get("vtt_text"):
        raise HTTPException(404, "No transcript yet for this project.")
    return {"vtt_text": project["vtt_text"], "duration": project["duration"]}


@app.get("/api/project/{project_id}/cues")
async def get_cues(project_id: str):
    """Raw Whisper cues for Mode 1 (fully manual editing) — one checkbox
    per cue in the frontend, no AI, no outline."""
    project = _get_project(project_id)
    if not project.get("vtt_text"):
        raise HTTPException(404, "No transcript yet for this project.")

    cues = parse_vtt(project["vtt_text"])
    return {"cues": [{"start": c.start, "end": c.end, "text": c.text} for c in cues]}


@app.post("/api/cues-cut")
async def cues_cut(project_id: str = Form(...), cues_json: str = Form(...)):
    """Turn user-selected raw cues directly into cuts, without any AI —
    each selected cue's own [start, end) range is already a removable
    range, same idea as /api/outline-cuts but one level more primitive
    (cue-granularity instead of outline-section-granularity)."""
    project = _get_project(project_id)

    try:
        raw_cues = json.loads(cues_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid cues JSON")

    cuts = [
        Cut(start=float(c["start"]), end=float(c["end"]), text=c.get("text", ""), reason="Removed via manual cue selection")
        for c in raw_cues
    ]

    if not cuts:
        raise HTTPException(400, "No cues selected.")

    cuts.extend(_untranscribed_edge_cuts(project))

    return _build_cuts_response(cuts, project["duration"])


def _untranscribed_edge_cuts(project: dict) -> list[Cut]:
    """Cuts for the video before the first cue and after the last one (Mode 1
    and Mode 3). Nothing is said there, so there is no cue the user or the AI
    could remove — without this, e.g. an end screen after the last words
    would stay in the edited video. Pauses between cues are left alone."""
    duration = project.get("duration")
    cues = parse_vtt(project.get("vtt_text") or "")
    if not duration or not cues:
        return []

    first_start = min(c.start for c in cues)
    last_end = max(c.end for c in cues)
    cuts: list[Cut] = []
    if first_start >= MIN_UNCOVERED_SECONDS:
        cuts.append(Cut(start=0.0, end=first_start, reason=NO_TEXT_REASON))
    if duration - last_end >= MIN_UNCOVERED_SECONDS:
        cuts.append(Cut(start=last_end, end=duration, reason=NO_TEXT_REASON))
    return cuts


def _build_cuts_response(
    cuts: list[Cut],
    duration: float,
    warnings: list[str] | None = None,
    change_log: str = "",
    questions: str = "",
) -> dict:
    normalized = normalize_cuts(cuts, duration)
    removed_seconds = sum(c.end - c.start for c in normalized)

    return {
        "cuts": [
            {"start": c.start, "end": c.end, "text": c.text, "reason": c.reason}
            for c in normalized
        ],
        "removed_seconds": removed_seconds,
        "original_duration": duration,
        "new_duration": max(0.0, duration - removed_seconds),
        "warnings": warnings or [],
        "change_log": change_log,
        "questions": questions,
    }


def _cuts_response(parsed: ParsedResponse, project: dict) -> dict:
    cuts = [
        Cut(start=r.start, end=r.end, text=r.text, reason=r.reason)
        for r in parsed.removed
    ]
    cuts.extend(_untranscribed_edge_cuts(project))
    return _build_cuts_response(
        cuts, project["duration"], warnings=parsed.warnings, change_log=parsed.change_log, questions=parsed.questions
    )


@app.post("/api/parse")
async def parse_ai_text(project_id: str = Form(...), ai_response: str = Form(...)):
    project = _get_project(project_id)
    parsed = parse_ai_response(ai_response)
    return _cuts_response(parsed, project)


@app.get("/api/workspace/video")
async def workspace_video():
    """Serves the current workspace video so the browser can restore the
    preview after a page reload, without needing to re-ingest (which would
    wipe outline.md/cuts.md as if it were a new project)."""
    matches = list(WORKSPACE_DIR.glob("video.*"))
    if not matches:
        raise HTTPException(404, "No video in the workspace yet.")
    return FileResponse(matches[0])


@app.get("/api/workspace/outline")
async def workspace_outline():
    if not OUTLINE_PATH.exists():
        raise HTTPException(404, "No outline.md yet — ask Claude to build the outline first.")

    text = OUTLINE_PATH.read_text(encoding="utf-8")
    sections = parse_outline(text)

    if not sections and text.strip():
        raise HTTPException(
            422,
            "outline.md exists but doesn't match the expected "
            "'## Title (start - end)' heading format — see AI_EDITING_INSTRUCTIONS.md.",
        )

    return {
        "sections": [
            {"level": s.level, "title": s.title, "start": s.start, "end": s.end, "body": s.body}
            for s in sections
        ]
    }


@app.post("/api/outline-cuts")
async def outline_cuts(project_id: str = Form(...), sections_json: str = Form(...)):
    """Turn user-selected outline sections directly into cuts, without
    asking an AI — the outline's timestamps already come straight from the
    original cues (see AI_EDITING_INSTRUCTIONS.md), so a section the user
    picked for removal can be treated as a cut covering exactly that
    section's time range. Overlap between a selected parent paragraph and
    its sub-paragraphs is handled by the normal merge logic."""
    project = _get_project(project_id)

    try:
        raw_sections = json.loads(sections_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid sections JSON")

    cuts = [
        Cut(start=float(s["start"]), end=float(s["end"]), text=s.get("title", ""), reason="Removed via outline selection")
        for s in raw_sections
    ]

    if not cuts:
        raise HTTPException(400, "No sections selected.")

    cuts.extend(_uncovered_by_outline_cuts(project["duration"]))

    return _build_cuts_response(cuts, project["duration"])


# Gaps shorter than this between outline sections are timing noise, not
# untranscribed video worth cutting.
MIN_UNCOVERED_SECONDS = 0.05
NO_TEXT_REASON = "No transcript text in this part"


def _uncovered_by_outline_cuts(duration: float | None) -> list[Cut]:
    """Cuts for the parts of the video that no outline section covers — e.g.
    an end screen or outro music after the last transcribed words. With no
    text there, they can't appear in the outline, so the user could never
    tick them off; leaving them in would tack them onto the edited video."""
    if not duration or not OUTLINE_PATH.exists():
        return []

    sections = parse_outline(OUTLINE_PATH.read_text(encoding="utf-8"))
    ranges = sorted((s.start, s.end) for s in sections if s.end > s.start)
    if not ranges:
        return []

    cuts: list[Cut] = []
    position = 0.0
    for start, end in ranges:
        if start - position >= MIN_UNCOVERED_SECONDS:
            cuts.append(Cut(start=position, end=start, reason=NO_TEXT_REASON))
        position = max(position, end)
    if duration - position >= MIN_UNCOVERED_SECONDS:
        cuts.append(Cut(start=position, end=duration, reason=NO_TEXT_REASON))
    return cuts


def _build_voice_chunks(
    project: dict, normalized_cuts: list[Cut], include_additions: bool = True
) -> tuple[list[TextChunk], int, int, str]:
    """One chunk per outline paragraph/sub-paragraph when workspace/outline.md
    exists and parses (matching whatever granularity the AI outline already
    chose), otherwise falls back to ~500-character chunks. Used both when
    generating/listing chunks and when re-deriving chunk indices at render
    time — these must stay in lockstep, or a chunk's audio could get
    matched to the wrong index.

    With `include_additions`, the project's loaded new parts (Mode 4) are
    slotted in as extra "added" chunks. Without it, this is exactly the list
    script.md numbers its sections from."""

    all_cues = parse_vtt(project["vtt_text"])
    surviving_cues = kept_cues(all_cues, normalized_cuts)

    outline_sections = []
    if OUTLINE_PATH.exists():
        outline_sections = parse_outline(OUTLINE_PATH.read_text(encoding="utf-8"))

    if outline_sections:
        chunks = chunk_by_outline(surviving_cues, outline_sections)
        mode = "outline"
    else:
        chunks = chunk_kept_cues(surviving_cues)
        mode = "character-count"

    if include_additions and project.get("additions"):
        chunks = merge_additions(chunks, project["additions"])

    return chunks, len(surviving_cues), len(all_cues), mode


def _parse_cuts(project: dict, cuts_json: str) -> list[Cut]:
    try:
        raw_cuts = json.loads(cuts_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid cuts JSON")
    cuts = [Cut(start=float(c["start"]), end=float(c["end"])) for c in raw_cuts]
    return normalize_cuts(cuts, project["duration"])


def _clear_chunk_audio() -> None:
    """Voice-over files are keyed by chunk index; adding/removing new parts
    shifts the indices, so old audio would land on the wrong chunk."""
    if CHUNK_AUDIO_DIR.exists():
        for old in CHUNK_AUDIO_DIR.glob("chunk_*"):
            old.unlink()


def _public_additions(project: dict) -> list[dict]:
    return [
        {k: a[k] for k in ("title", "text", "position", "section", "anchor")}
        for a in project.get("additions") or []
    ]


@app.post("/api/script")
async def write_script(project_id: str = Form(...), cuts_json: str = Form(...)):
    """Writes workspace/script.md — the kept text as numbered sections — for
    Claude to read in Mode 4 (adding new parts)."""
    project = _get_project(project_id)
    if not project.get("vtt_text"):
        raise HTTPException(400, "No transcript yet for this project.")

    chunks, _, _, _ = _build_voice_chunks(project, _parse_cuts(project, cuts_json), include_additions=False)
    if not chunks:
        raise HTTPException(400, "Nothing is left after the cuts — there's no script to add to.")

    SCRIPT_PATH.write_text(build_script(chunks, project.get("language", "")), encoding="utf-8")
    return {"sections": len(chunks)}


@app.post("/api/additions/load")
async def load_additions(project_id: str = Form(...), cuts_json: str = Form(...)):
    """Reads Claude's workspace/additions.md against the same sections
    script.md was numbered from, and makes those new parts part of the
    project's voice-over chunks."""
    project = _get_project(project_id)
    if not ADDITIONS_PATH.exists():
        raise HTTPException(404, "No additions.md yet — ask Claude to write the new parts first.")

    chunks, _, _, _ = _build_voice_chunks(project, _parse_cuts(project, cuts_json), include_additions=False)
    additions, warnings = parse_additions(
        ADDITIONS_PATH.read_text(encoding="utf-8"), chunks, project["duration"]
    )
    if not additions:
        raise HTTPException(422, " ".join(warnings))

    # Reloading the same parts keeps the footage already picked for them.
    previous_clips = {
        (a["title"], a["text"]): a.get("clips", []) for a in project.get("additions") or []
    }
    project["additions"] = [
        {**a.__dict__, "clips": previous_clips.get((a.title, a.text), [])} for a in additions
    ]
    _clear_chunk_audio()
    return {
        "additions": _public_additions(project),
        "warnings": warnings,
        "section_titles": [c.title for c in chunks],
    }


@app.post("/api/additions/clear")
async def clear_additions(project_id: str = Form(...)):
    """"Skip" in the app: render without any new parts."""
    project = _get_project(project_id)
    if project.get("additions"):
        project["additions"] = []
        _clear_chunk_audio()
    return {"additions": []}


# --- Footage for added parts (B-roll, see broll.py) ------------------------

# Local Piper voice families, by the language picked at ingest — used to
# measure roughly how long each added part's voice-over will be.
_PIPER_PREFIX_BY_LANGUAGE = {
    "English": "en_", "Russian": "ru_", "Spanish": "es_", "French": "fr_", "German": "de_",
    "Italian": "it_", "Portuguese": "pt_", "Ukrainian": "uk_", "Turkish": "tr_",
}


def _sources(project: dict) -> dict[str, dict]:
    """Every video footage can be picked from: the main video first, then
    the extra YouTube links in the order they were added."""
    main = {
        "id": broll.MAIN_SOURCE_ID,
        "url": project.get("source_url"),
        "title": "Main video",
        "status": "ready" if project.get("video_path") else "downloading",
        "progress": 1.0,
        "message": "",
        "error": None,
        "path": project.get("video_path"),
        "duration": project.get("duration"),
        "has_filmstrip": True,  # made on first request
    }
    return {broll.MAIN_SOURCE_ID: main, **project.setdefault("sources", {})}


def _public_source(source: dict) -> dict:
    return {k: v for k, v in source.items() if k != "path"}


def _get_source(project: dict, source_id: str) -> dict:
    source = _sources(project).get(source_id)
    if not source:
        raise HTTPException(404, "Unknown video source.")
    return source


def _estimate_part_seconds(project: dict, addition: dict) -> float:
    """Approximate voice-over length plus the pauses around it — how much
    footage the part needs. Measured once per text with a local voice."""
    cached = addition.get("estimate")
    if cached and cached.get("text") == addition["text"]:
        return cached["seconds"]

    prefix = _PIPER_PREFIX_BY_LANGUAGE.get(project.get("language", ""))
    voices = [v["name"] for v in list_available_voices()] if prefix else []
    voice = next((v for v in voices if v.startswith(prefix)), None) if prefix else None

    def measure(text: str) -> float | None:
        if voice is None:
            return None
        CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path = CHUNK_AUDIO_DIR / "_broll_estimate.wav"
        synthesize_to_wav(text, voice, str(path), rate=1.0)
        try:
            return get_duration(str(path))
        finally:
            path.unlink(missing_ok=True)

    seconds = broll.estimate_seconds(addition["text"], measure) + 2 * INSERT_PAD_SECONDS
    addition["estimate"] = {"text": addition["text"], "seconds": seconds}
    return seconds


@app.get("/api/broll")
def broll_state(project_id: str):
    """Everything the footage picker needs: the video sources and, per added
    part, how long it roughly runs and the clips picked for it so far."""
    project = _get_project(project_id)
    additions = project.get("additions") or []

    # The main video's timeline thumbnails take a few seconds the first time;
    # start them now so they're usually ready when a picker opens.
    main = _sources(project)[broll.MAIN_SOURCE_ID]
    if main["path"] and not broll.filmstrip_path(main["path"]).exists():
        threading.Thread(
            target=broll.ensure_filmstrip, args=(main["path"], main["duration"]), daemon=True
        ).start()

    return {
        "sources": [_public_source(s) for s in _sources(project).values()],
        "parts": [
            {
                "index": index,
                "title": a["title"],
                "text": a["text"],
                "estimate_seconds": _estimate_part_seconds(project, a),
                "clips": a.get("clips", []),
            }
            for index, a in enumerate(additions)
        ],
    }


@app.get("/api/broll/sources")
def broll_sources(project_id: str):
    """Polled while extra videos download."""
    project = _get_project(project_id)
    return {"sources": [_public_source(s) for s in _sources(project).values()]}


@app.post("/api/broll/sources")
def add_broll_source(project_id: str = Form(...), url: str = Form(...)):
    project = _get_project(project_id)
    url = url.strip()
    if not url:
        raise HTTPException(400, "Paste a YouTube link first.")

    source = broll.new_source(url)
    project.setdefault("sources", {})[source["id"]] = source
    threading.Thread(
        target=broll.download_source,
        args=(source, LIBRARY_DIR, UPLOAD_DIR / project_id / "sources"),
        daemon=True,
    ).start()
    return {"source": _public_source(source)}


@app.post("/api/broll/sources/remove")
def remove_broll_source(project_id: str = Form(...), source_id: str = Form(...)):
    """Forgets an extra video, and every clip picked from it."""
    project = _get_project(project_id)
    if source_id == broll.MAIN_SOURCE_ID:
        raise HTTPException(400, "The main video can't be removed.")
    project.setdefault("sources", {}).pop(source_id, None)
    for addition in project.get("additions") or []:
        addition["clips"] = [c for c in addition.get("clips", []) if c.get("source_id") != source_id]
    return broll_state(project_id)


@app.get("/api/broll/sources/{project_id}/{source_id}/video")
def broll_source_video(project_id: str, source_id: str):
    source = _get_source(_get_project(project_id), source_id)
    if source["status"] != "ready":
        raise HTTPException(409, "This video isn't downloaded yet.")
    return FileResponse(source["path"])


@app.get("/api/broll/sources/{project_id}/{source_id}/filmstrip")
def broll_source_filmstrip(project_id: str, source_id: str):
    source = _get_source(_get_project(project_id), source_id)
    if source["status"] != "ready":
        raise HTTPException(409, "This video isn't downloaded yet.")
    path = broll.ensure_filmstrip(source["path"], source["duration"])
    if path is None:
        raise HTTPException(500, "Could not make the timeline thumbnails.")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/broll/clips")
def set_broll_clips(project_id: str = Form(...), part_index: int = Form(...), clips_json: str = Form(...)):
    """Replaces one added part's picked clips (in play order)."""
    project = _get_project(project_id)
    additions = project.get("additions") or []
    if not 0 <= part_index < len(additions):
        raise HTTPException(404, "No such new part.")
    try:
        raw = json.loads(clips_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid clips JSON")

    sources = _sources(project)
    clips = []
    for clip in raw:
        source = sources.get(clip.get("source_id"))
        if not source or source["status"] != "ready":
            raise HTTPException(400, "A clip uses a video that isn't available.")
        start = max(0.0, float(clip["start"]))
        end = min(float(source["duration"]), float(clip["end"]))
        if end - start < 0.1:
            continue
        clips.append({"source_id": source["id"], "start": round(start, 3), "end": round(end, 3)})

    additions[part_index]["clips"] = clips
    return {"clips": clips}


@app.post("/api/transcript-chunks")
async def transcript_chunks(project_id: str = Form(...), cuts_json: str = Form(...)):
    """Text of everything the current cuts would NOT remove, split into
    voice-over chunks — one per outline paragraph/sub-paragraph if an AI
    outline exists, otherwise ~500-character chunks as a fallback."""
    project = _get_project(project_id)

    if not project.get("vtt_text"):
        raise HTTPException(400, "No transcript yet for this project.")

    try:
        raw_cuts = json.loads(cuts_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid cuts JSON")

    cuts = [Cut(start=float(c["start"]), end=float(c["end"])) for c in raw_cuts]
    normalized_cuts = normalize_cuts(cuts, project["duration"])

    chunks, kept_cue_count, total_cue_count, mode = _build_voice_chunks(project, normalized_cuts)

    return {
        "chunks": [
            {
                "text": c.text,
                "start": c.start,
                "end": c.end,
                "slot_duration": c.slot_duration,
                "title": c.title,
                "kind": c.kind,
            }
            for c in chunks
        ],
        "kept_cue_count": kept_cue_count,
        "total_cue_count": total_cue_count,
        "chunking_mode": mode,
    }


def _chunk_audio_result(chunk_index: int, audio_path: Path, slot_duration: float) -> dict:
    try:
        audio_duration = get_duration(str(audio_path))
    except FFmpegNotFoundError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"Could not read audio file: {exc}")

    overflow = max(0.0, audio_duration - slot_duration)

    return {
        "chunk_index": chunk_index,
        "audio_duration": audio_duration,
        "slot_duration": slot_duration,
        "fits": overflow <= 0.05,
        "overflow_seconds": overflow,
    }


@app.post("/api/transcript-chunks/audio")
async def upload_chunk_audio(
    project_id: str = Form(...),
    chunk_index: int = Form(...),
    slot_duration: float = Form(...),
    audio: UploadFile = File(...),
):
    """Store a voice-over recording for one chunk and check it isn't longer
    than the video slot it would replace."""
    _get_project(project_id)

    CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "audio.mp3").suffix or ".mp3"

    for old in CHUNK_AUDIO_DIR.glob(f"chunk_{chunk_index:04d}.*"):
        old.unlink()

    audio_path = CHUNK_AUDIO_DIR / f"chunk_{chunk_index:04d}{suffix}"
    with open(audio_path, "wb") as f:
        while data := await audio.read(1024 * 1024):
            f.write(data)

    return _chunk_audio_result(chunk_index, audio_path, slot_duration)


@app.get("/api/tts/voices")
async def tts_voices():
    voices = [{**v, "provider": "piper"} for v in list_available_voices()]
    voices += [{**v, "provider": "azure"} for v in azure_tts.list_available_voices()]
    return {"voices": voices}


@app.get("/api/tts/azure-usage")
async def azure_usage():
    return azure_tts.get_usage()


def _synthesize_chunk(index: int, text: str, voice: str, rate: float = 1.0) -> Path:
    """Dispatches to Piper (free, offline, no API key) or Azure AI Speech
    (paid cloud API, needs AZURE_SPEECH_KEY/REGION) depending on which voice
    was picked, writing the result to workspace/chunk_audio/chunk_{index}.*

    `rate` is a speed multiplier (1.0 = normal) for both providers: Azure maps
    it to SSML prosody, Piper to phoneme length + sentence pauses."""

    CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for old in CHUNK_AUDIO_DIR.glob(f"chunk_{index:04d}.*"):
        old.unlink()

    if voice in PIPER_KNOWN_VOICES:
        audio_path = CHUNK_AUDIO_DIR / f"chunk_{index:04d}.wav"
        synthesize_to_wav(text, voice, str(audio_path), rate=rate)
    elif voice in azure_tts.KNOWN_VOICES:
        audio_path = CHUNK_AUDIO_DIR / f"chunk_{index:04d}.mp3"
        azure_tts.synthesize_to_file(text, voice, str(audio_path), rate=rate)
    else:
        raise ValueError(f"Unknown voice: {voice}")

    return audio_path


@app.post("/api/transcript-chunks/tts")
async def generate_chunk_tts(
    project_id: str = Form(...),
    chunk_index: int = Form(...),
    text: str = Form(...),
    slot_duration: float = Form(...),
    voice: str = Form(...),
    rate: float = Form(1.0),
):
    """Generate a chunk's voice-over and check it isn't longer than the
    video slot it would replace."""
    _get_project(project_id)

    try:
        audio_path = _synthesize_chunk(chunk_index, text, voice, rate=rate)
    except VoiceNotAvailableError as exc:
        raise HTTPException(400, str(exc))
    except azure_tts.AzureNotConfiguredError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    return _chunk_audio_result(chunk_index, audio_path, slot_duration)


@app.get("/api/transcript-chunks/audio/{chunk_index}")
async def get_chunk_audio(chunk_index: int):
    """Serves whatever audio currently exists for one chunk (generated or
    uploaded) so the app can play it back inline."""
    matches = [
        path
        for path in CHUNK_AUDIO_DIR.glob(f"chunk_{chunk_index:04d}.*")
        if not path.name.startswith("_music")
    ]
    if not matches:
        raise HTTPException(404, "No audio generated for this chunk yet.")
    return FileResponse(matches[0])


@app.get("/api/workspace/cuts")
async def workspace_cuts(project_id: str):
    project = _get_project(project_id)

    if not CUTS_PATH.exists():
        raise HTTPException(404, "No cuts.md yet — ask Claude to produce the cuts first.")

    text = CUTS_PATH.read_text(encoding="utf-8")
    parsed = parse_ai_response(text)
    return _cuts_response(parsed, project)


def _run_render(project_id: str, keep_segments: list[tuple[float, float]], output_path: Path) -> None:
    project = PROJECTS[project_id]
    try:
        render_video(project["video_path"], str(output_path), keep_segments)
        project["status"] = "done"
        project["output_path"] = str(output_path)
    except Exception as exc:
        project["status"] = "error"
        project["error"] = str(exc)


@app.post("/api/render")
async def render(project_id: str = Form(...), cuts_json: str = Form(...)):
    project = _get_project(project_id)

    try:
        raw_cuts = json.loads(cuts_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid cuts JSON")

    cuts = [Cut(start=float(c["start"]), end=float(c["end"])) for c in raw_cuts]
    normalized = normalize_cuts(cuts, project["duration"])
    keep_segments = calculate_keep_segments(normalized, project["duration"])

    if not keep_segments:
        raise HTTPException(400, "Every segment was cut — nothing would be left to render.")

    output_name = f"{project_id}_edited.mp4"
    output_path = OUTPUT_DIR / output_name

    project["status"] = "rendering"
    project["error"] = None

    thread = threading.Thread(
        target=_run_render, args=(project_id, keep_segments, output_path), daemon=True
    )
    thread.start()

    return {"status": "started"}


VoiceLayout = tuple[list[tuple[float, str]], list[tuple[float, float]], list[list[tuple[str, float, float]]]]


def _voice_layout(
    project: dict,
    entries: list[tuple[str, float, Path | None, int]],
    keep_segments: list[tuple[float, float]],
) -> VoiceLayout:
    """entries: (kind, start, audio_path, addition_index) per chunk, in chunk
    order. Returns the voice overlays (output start, path), the inserts
    (anchor, duration) and each insert's picked footage (see broll.py) for
    render_video_with_audio. An added chunk only becomes an insert once it
    has audio — its voice-over decides how long the video pauses for it."""
    inserts = []
    insert_clips = []
    added_audio = []
    additions = project.get("additions") or []
    sources = _sources(project)
    for kind, start, path, addition_index in entries:
        if kind == "added" and path is not None:
            inserts.append((start, get_duration(str(path)) + 2 * INSERT_PAD_SECONDS))
            added_audio.append(path)
            clips = additions[addition_index].get("clips", []) if 0 <= addition_index < len(additions) else []
            insert_clips.append(broll.clip_inputs(clips, sources))

    timeline = build_timeline(keep_segments, inserts)
    overlays = [
        (output_time(start, keep_segments, inserts), str(path))
        for kind, start, path, _ in entries
        if kind != "added" and path is not None
    ]
    overlays += [
        (insert_start + INSERT_PAD_SECONDS, str(path))
        for insert_start, path in zip(timeline.insert_starts, added_audio)
    ]
    return overlays, inserts, insert_clips


def _run_render_with_audio(
    project_id: str,
    keep_segments: list[tuple[float, float]],
    output_path: Path,
    keep_original_audio: bool,
    voice_overlays: list[tuple[float, str]],
    music_path: str | None,
    music_db: float,
    inserts: list[tuple[float, float]],
    insert_clips: list[list[tuple[str, float, float]]],
) -> None:
    project = PROJECTS[project_id]
    try:
        render_video_with_audio(
            project["video_path"],
            str(output_path),
            keep_segments,
            keep_original_audio,
            voice_overlays,
            music_path,
            music_db,
            inserts,
            insert_clips,
        )
        project["status"] = "done"
        project["output_path"] = str(output_path)
    except Exception as exc:
        project["status"] = "error"
        project["error"] = str(exc)


@app.post("/api/render-with-audio")
async def render_with_audio(
    project_id: str = Form(...),
    cuts_json: str = Form(...),
    keep_original_audio: bool = Form(...),
    music_db: float = Form(-5.0),
    music: UploadFile | None = File(None),
):
    """Like /api/render, but with a custom audio mix: optionally drop the
    original audio track entirely, optionally loop a background music file
    under the whole video, and overlay every already-generated chunk
    voice-over (workspace/chunk_audio/) at its mapped position in the final
    timeline."""
    project = _get_project(project_id)

    try:
        raw_cuts = json.loads(cuts_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid cuts JSON")

    cuts = [Cut(start=float(c["start"]), end=float(c["end"])) for c in raw_cuts]
    normalized = normalize_cuts(cuts, project["duration"])
    keep_segments = calculate_keep_segments(normalized, project["duration"])

    if not keep_segments:
        raise HTTPException(400, "Every segment was cut — nothing would be left to render.")

    # Re-derive the same chunk list the user saw when generating/uploading
    # voice-over (same cuts -> same chunk indices), then map each chunk
    # that has audio to its position in the OUTPUT timeline.
    voice_overlays: list[tuple[float, str]] = []
    inserts: list[tuple[float, float]] = []
    insert_clips: list[list[tuple[str, float, float]]] = []
    if project.get("vtt_text") and CHUNK_AUDIO_DIR.exists():
        chunks, _, _, _ = _build_voice_chunks(project, normalized)
        voice_overlays, inserts, insert_clips = _voice_layout(
            project,
            [
                (chunk.kind, chunk.start, _chunk_audio_path(index), chunk.addition_index)
                for index, chunk in enumerate(chunks)
            ],
            keep_segments,
        )

    music_path = None
    if music is not None:
        CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(music.filename or "music.mp3").suffix or ".mp3"
        music_file_path = CHUNK_AUDIO_DIR / f"_music_upload{suffix}"
        with open(music_file_path, "wb") as f:
            while data := await music.read(1024 * 1024):
                f.write(data)
        music_path = str(music_file_path)

    output_name = f"{project_id}_edited.mp4"
    output_path = OUTPUT_DIR / output_name

    project["status"] = "rendering"
    project["error"] = None

    thread = threading.Thread(
        target=_run_render_with_audio,
        args=(
            project_id,
            keep_segments,
            output_path,
            keep_original_audio,
            voice_overlays,
            music_path,
            music_db,
            inserts,
            insert_clips,
        ),
        daemon=True,
    )
    thread.start()

    return {"status": "started"}


# --- Audio option 2: automatic TTS -----------------------------------------
#
# For every chunk: render it with a free local Piper voice to predict its
# duration, pick the speed (duration_fit.AUTO_RATES) that best fills the
# chunk's video window, and only then generate the real voice-over. Chunks
# that can't fit (too long even at the fastest speed, or leaving more than
# MAX_GAP_SECONDS of silence even at the slowest) are flagged and NOT sent to
# Azure, which saves characters. If anything is flagged, the run stops in
# "needs_review": the user edits those chunks (recheck) or accepts them as-is,
# then continues the render.

_ESTIMATE_PATH_NAME = "_estimate.wav"
_RESOLVED_STATUSES = ("ok", "accepted")


def _estimator_voice(voice: str) -> str | None:
    """Piper voice used to predict durations. A Piper voice predicts
    itself. Azure voices use one calibrated Russian Piper voice."""
    if voice in PIPER_KNOWN_VOICES:
        return voice
    available = [v["name"] for v in list_available_voices() if v["name"].startswith("ru_")]
    if ESTIMATOR_PIPER_VOICE in available:
        return ESTIMATOR_PIPER_VOICE
    return available[0] if available else None


def _chunk_audio_path(index: int) -> Path | None:
    matches = [
        path
        for path in CHUNK_AUDIO_DIR.glob(f"chunk_{index:04d}.*")
        if not path.name.startswith("_music")
    ]
    return matches[0] if matches else None


def _azure_correction(run: dict) -> float:
    """Median of real-Azure / Piper-predicted durations seen so far in this
    run. Corrects the prediction for the voice/text at hand, so later chunks
    need fewer retries."""
    ratios = sorted(run["ratios"])
    if not ratios:
        return 1.0
    mid = len(ratios) // 2
    return ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2


def _auto_tts_chunk(run: dict, record: dict, force_rate: float | None = None) -> None:
    """Predict, choose a speed and (if it fits) generate one chunk's
    voice-over. Updates `record` in place.

    With `force_rate`, skips the prediction and generates at that speed no
    matter what. That's the "accept anyway" path."""
    index = record["index"]
    window = record["slot_duration"]
    voice = run["voice"]
    is_azure = voice in azure_tts.KNOWN_VOICES

    for old in CHUNK_AUDIO_DIR.glob(f"chunk_{index:04d}.*"):
        old.unlink()
    record.update(audio_duration=None, has_audio=False, message=None)

    if record.get("kind") == "added":
        # A new part has no video window to fit: the video pauses for as
        # long as its voice-over runs, so it's simply spoken at normal speed.
        rate = force_rate or 1.0
        audio_path = _synthesize_chunk(index, record["text"], voice, rate=rate)
        if is_azure:
            run["azure_chars"] += len(record["text"])
        record.update(
            rate=rate, estimate=None, audio_duration=get_duration(str(audio_path)), has_audio=True, status="ok"
        )
        return

    if force_rate is None:
        estimator = _estimator_voice(voice)
        if estimator is None:
            # Nothing to predict with: just generate at normal speed.
            choice = duration_fit.RateChoice(1.0, 0.0, "ok")
        else:
            CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            estimate_path = CHUNK_AUDIO_DIR / _ESTIMATE_PATH_NAME
            synthesize_to_wav(record["text"], estimator, str(estimate_path), rate=1.0)
            duration_1x = get_duration(str(estimate_path))
            estimate_path.unlink(missing_ok=True)
            if is_azure:
                duration_1x *= _azure_correction(run)
            choice = duration_fit.choose_rate(duration_1x, window, voice if is_azure else None)

        record.update(rate=choice.rate, estimate=choice.estimate)
        if choice.verdict != "ok":
            record["status"] = choice.verdict
            return
        rate = choice.rate
    else:
        rate = force_rate
        record.update(rate=rate, estimate=None)

    def generate(at_rate: float) -> float:
        audio_path = _synthesize_chunk(index, record["text"], voice, rate=at_rate)
        if is_azure:
            run["azure_chars"] += len(record["text"])
        return get_duration(str(audio_path))

    audio_duration = generate(rate)
    if is_azure and record.get("estimate"):
        run["ratios"].append(audio_duration / record["estimate"])

    verdict = duration_fit.judge_actual(audio_duration, window)
    if verdict == "too_long" and force_rate is None:
        faster = duration_fit.next_faster_rate(rate)
        if faster is not None:
            rate = faster
            record["rate"] = rate
            audio_duration = generate(rate)
            verdict = duration_fit.judge_actual(audio_duration, window)

    record.update(audio_duration=audio_duration, has_audio=True)
    record["status"] = "accepted" if force_rate is not None else verdict


def _auto_tts_layout(project: dict, run: dict) -> VoiceLayout:
    return _voice_layout(
        project,
        [
            (r.get("kind", "original"), r["start"], _chunk_audio_path(r["index"]), r.get("addition_index", -1))
            for r in run["chunks"]
        ],
        run["keep_segments"],
    )


def _auto_tts_render(project_id: str) -> None:
    project = PROJECTS[project_id]
    run = project["auto_tts"]
    try:
        project["status"] = "rendering"
        project["phase"] = "rendering"
        project["phase_message"] = "Rendering video…"
        overlays, inserts, insert_clips = _auto_tts_layout(project, run)
        render_video_with_audio(
            project["video_path"],
            str(run["output_path"]),
            run["keep_segments"],
            False,
            overlays,
            inserts=inserts,
            insert_clips=insert_clips,
        )
        project["status"] = "done"
        project["phase"] = "done"
        project["progress"] = 1.0
        project["output_path"] = str(run["output_path"])
    except Exception as exc:
        project["status"] = "error"
        project["error"] = str(exc)


def _run_auto_tts(project_id: str) -> None:
    project = PROJECTS[project_id]
    run = project["auto_tts"]
    try:
        total = len(run["chunks"])
        for position, record in enumerate(run["chunks"]):
            project["status"] = "generating_voiceover"
            project["phase"] = "generating_voiceover"
            project["phase_message"] = f"Generating voice-over… chunk {position + 1}/{total}"
            project["progress"] = position / total if total else 0.0
            _auto_tts_chunk(run, record)

        if any(r["status"] not in _RESOLVED_STATUSES for r in run["chunks"]):
            project["status"] = "needs_review"
            project["phase"] = "needs_review"
            project["phase_message"] = ""
            return
    except Exception as exc:
        project["status"] = "error"
        project["error"] = str(exc)
        return

    _auto_tts_render(project_id)


def _public_auto_tts(run: dict) -> dict:
    return {
        "voice": run["voice"],
        "azure_chars": run["azure_chars"],
        "max_gap_seconds": duration_fit.MAX_GAP_SECONDS,
        "chunks": run["chunks"],
    }


@app.post("/api/auto-tts")
def auto_tts(
    project_id: str = Form(...),
    cuts_json: str = Form(...),
    voice: str = Form(...),
):
    """Audio Option 2: automatic TTS. Generates every chunk's voice-over
    with an automatically chosen speed, then renders. If some chunks can't
    fit, it stops in "needs_review" (see /api/auto-tts/review)."""
    project = _get_project(project_id)

    if not project.get("vtt_text"):
        raise HTTPException(400, "No transcript yet for this project.")
    if voice not in PIPER_KNOWN_VOICES and voice not in azure_tts.KNOWN_VOICES:
        raise HTTPException(400, f"Unknown voice: {voice}")

    try:
        raw_cuts = json.loads(cuts_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid cuts JSON")

    cuts = [Cut(start=float(c["start"]), end=float(c["end"])) for c in raw_cuts]
    normalized = normalize_cuts(cuts, project["duration"])
    keep_segments = calculate_keep_segments(normalized, project["duration"])

    if not keep_segments:
        raise HTTPException(400, "Every segment was cut — nothing would be left to render.")

    chunks, _, _, _ = _build_voice_chunks(project, normalized)

    # Clear audio left from earlier runs, so a stale file can't be overlaid.
    if CHUNK_AUDIO_DIR.exists():
        for old in CHUNK_AUDIO_DIR.glob("chunk_*"):
            old.unlink()

    project["auto_tts"] = {
        "voice": voice,
        "keep_segments": keep_segments,
        "output_path": OUTPUT_DIR / f"{project_id}_edited.mp4",
        "ratios": [],
        "azure_chars": 0,
        "chunks": [
            {
                "index": index,
                "title": chunk.title,
                "text": chunk.text,
                "start": chunk.start,
                "end": chunk.end,
                "slot_duration": chunk.slot_duration,
                "kind": chunk.kind,
                "addition_index": chunk.addition_index,
                "status": "pending",
                "rate": None,
                "estimate": None,
                "audio_duration": None,
                "has_audio": False,
            }
            for index, chunk in enumerate(chunks)
        ],
    }
    project["status"] = "generating_voiceover"
    project["error"] = None

    threading.Thread(target=_run_auto_tts, args=(project_id,), daemon=True).start()
    return {"status": "started"}


def _get_auto_tts_run(project_id: str) -> tuple[dict, dict]:
    project = _get_project(project_id)
    run = project.get("auto_tts")
    if not run:
        raise HTTPException(404, "No automatic voice-over run for this project.")
    return project, run


def _get_auto_tts_record(run: dict, chunk_index: int) -> dict:
    if not 0 <= chunk_index < len(run["chunks"]):
        raise HTTPException(404, "No such chunk.")
    return run["chunks"][chunk_index]


def _call_tts(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except VoiceNotAvailableError as exc:
        raise HTTPException(400, str(exc))
    except azure_tts.AzureNotConfiguredError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


@app.get("/api/auto-tts/review")
def auto_tts_review(project_id: str):
    _, run = _get_auto_tts_run(project_id)
    return _public_auto_tts(run)


@app.post("/api/auto-tts/recheck")
def auto_tts_recheck(project_id: str = Form(...), chunk_index: int = Form(...), text: str = Form(...)):
    """Edited text for a flagged chunk: predict again for free, and spend
    Azure characters only if it now fits."""
    _, run = _get_auto_tts_run(project_id)
    record = _get_auto_tts_record(run, chunk_index)
    record["text"] = text
    _call_tts(_auto_tts_chunk, run, record)
    return {"chunk": record, "azure_chars": run["azure_chars"]}


@app.post("/api/auto-tts/accept")
def auto_tts_accept(project_id: str = Form(...), chunk_index: int = Form(...), text: str = Form(...)):
    """Keep a flagged chunk as it is. If it has no audio yet (it was
    flagged from the prediction), generate it now at the closest speed
    (fastest when too long, slowest when too short). A too-long voice-over
    is cut off at the end of its window in the final video."""
    _, run = _get_auto_tts_run(project_id)
    record = _get_auto_tts_record(run, chunk_index)

    if record["has_audio"] and record["text"] == text:
        record["status"] = "accepted"
    else:
        record["text"] = text
        rate = max(duration_fit.AUTO_RATES) if record["status"] == "too_long" else min(duration_fit.AUTO_RATES)
        _call_tts(_auto_tts_chunk, run, record, force_rate=rate)
    return {"chunk": record, "azure_chars": run["azure_chars"]}


@app.post("/api/auto-tts/continue")
def auto_tts_continue(project_id: str = Form(...)):
    project, run = _get_auto_tts_run(project_id)
    unresolved = [r["index"] + 1 for r in run["chunks"] if r["status"] not in _RESOLVED_STATUSES]
    if unresolved:
        raise HTTPException(400, f"Chunks still need attention: {', '.join(map(str, unresolved))}")

    project["status"] = "rendering"
    project["error"] = None
    threading.Thread(target=_auto_tts_render, args=(project_id,), daemon=True).start()
    return {"status": "started"}


@app.get("/api/status/{project_id}")
async def status(project_id: str):
    project = _get_project(project_id)

    response = {"status": project["status"]}

    if project.get("phase"):
        response["phase"] = project["phase"]
        response["phase_message"] = project.get("phase_message", "")
        response["progress"] = project.get("progress", 0.0)

    if project["status"] == "done" and project.get("output_path"):
        response["download_url"] = f"/api/download/{Path(project['output_path']).name}"

    if project["status"] == "done" and project.get("duration") is not None:
        response["duration"] = project["duration"]
        response["video_cached"] = bool(project.get("video_cached"))
        response["transcript_cached"] = bool(project.get("transcript_cached"))

    if project["status"] == "error":
        response["error"] = project.get("error")

    return response


@app.get("/api/download/{filename}")
async def download(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
