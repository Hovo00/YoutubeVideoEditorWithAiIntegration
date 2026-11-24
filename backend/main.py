"""FastAPI backend for VideoEditorY.

Single local process that serves both the API and the static frontend, so
the whole app is launched with one command on Windows or Linux (see
run.py). State is kept in memory since this is a single-user local tool.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import wave
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import azure_tts, broll, duration_fit, pauses, youtube_ingest
from .additions import build_script, merge_additions, parse_additions
from .chunker import TextChunk, chunk_by_outline, chunk_kept_cues, kept_cues
from .editor import (
    Cut,
    build_timeline,
    calculate_keep_segments,
    map_to_output_timeline,
    normalize_cuts,
    output_time,
)
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
# Written by Claude with the outline (Mode 2): where a voice-over may pause
# when it is much shorter than its video window (see backend/pauses.py).
PAUSES_PATH = WORKSPACE_DIR / "pauses.md"
# What the user wants to make and in which language (see /api/project/
# settings) — Claude reads it before every mode.
PROJECT_SETTINGS_PATH = WORKSPACE_DIR / "project.md"
# Which video the workspace holds (video_id, video_language, model, and
# output_language once chosen) — the key for saved outlines, see
# _outline_cache_dir.
SOURCE_PATH = WORKSPACE_DIR / "source.json"
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


# --- Saved AI outlines -------------------------------------------------------
# Claude's outline.md (and its pauses.md) is kept in the video's library
# folder, next to the cached transcript it was built from:
#   library/<video_id>/outlines/<video language>_<model>_to_<output language>/
# so opening the same video again restores it instead of asking Claude for
# a new one. It's saved whenever the outline is loaded in the app and before
# the workspace switches to another video, and removed only when the user
# deletes it in the app.


def _read_source() -> dict:
    try:
        return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_source(**fields) -> None:
    SOURCE_PATH.write_text(json.dumps({**_read_source(), **fields}), encoding="utf-8")


def _outline_cache_dir(source: dict | None = None) -> Path | None:
    """None until the video is a known YouTube video and the output
    language is chosen (a translated outline is a different outline)."""
    source = _read_source() if source is None else source
    if not source.get("video_id") or not source.get("output_language"):
        return None
    key = f"{source['video_language']}_{source['model']}_to_{source['output_language']}"
    return LIBRARY_DIR / source["video_id"] / "outlines" / key


def _save_outline_to_cache() -> bool:
    target = _outline_cache_dir()
    if target is None or not OUTLINE_PATH.exists():
        return False
    if not parse_outline(OUTLINE_PATH.read_text(encoding="utf-8")):
        return False  # don't keep a half-written or broken outline
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUTLINE_PATH, target / "outline.md")
    if PAUSES_PATH.exists():
        shutil.copyfile(PAUSES_PATH, target / "pauses.md")
    else:
        (target / "pauses.md").unlink(missing_ok=True)
    return True


def _restore_outline_from_cache() -> bool:
    """Copies the saved outline into the workspace, unless the workspace
    already has one (it may be newer, still being edited)."""
    target = _outline_cache_dir()
    if target is None or OUTLINE_PATH.exists() or not (target / "outline.md").exists():
        return False
    shutil.copyfile(target / "outline.md", OUTLINE_PATH)
    if (target / "pauses.md").exists():
        shutil.copyfile(target / "pauses.md", PAUSES_PATH)
    return True


def _has_saved_outline() -> bool:
    target = _outline_cache_dir()
    return bool(target and (target / "outline.md").exists())


def _mirror_into_workspace(video_path: Path, vtt_text: str, video_id: str | None, language: str) -> None:
    """Mirrors the current project's video + transcript into the fixed
    workspace/ folder so Claude Desktop/Claude Code always has a stable
    path to work with. This is a new "current project" — drop any previous
    video file (could have a different extension) and any stale outline/cuts
    output from whatever was there before (saving the previous video's
    outline first)."""

    _save_outline_to_cache()
    for old_video in WORKSPACE_DIR.glob("video.*"):
        old_video.unlink()
    shutil.copyfile(video_path, WORKSPACE_DIR / f"video{video_path.suffix}")
    (WORKSPACE_DIR / "subtitles.vtt").write_text(vtt_text, encoding="utf-8")
    OUTLINE_PATH.unlink(missing_ok=True)
    CUTS_PATH.unlink(missing_ok=True)
    SCRIPT_PATH.unlink(missing_ok=True)
    ADDITIONS_PATH.unlink(missing_ok=True)
    PAUSES_PATH.unlink(missing_ok=True)
    PROJECT_SETTINGS_PATH.unlink(missing_ok=True)
    SOURCE_PATH.unlink(missing_ok=True)
    shutil.rmtree(CHUNK_AUDIO_DIR, ignore_errors=True)
    _write_source(video_id=video_id, video_language=language, model=youtube_ingest.DEFAULT_WHISPER_MODEL)


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

        _mirror_into_workspace(video_path, vtt_text, video_id, language)

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
        "work_type": None,
        "output_language": "",
    }

    thread = threading.Thread(
        target=_run_ingest, args=(project_id, youtube_url, language), daemon=True
    )
    thread.start()

    return {"project_id": project_id}


# --- Step 2: what to make, and in which language ----------------------------

WORK_TYPES = {
    "revoice": "Re-voice edit (cut the video, voice it with TTS)",
    "review": "Review of a review (the reviewer's parts are quoted, AI review parts are added)",
}
# Languages the video can be translated into (only these have TTS voices).
OUTPUT_LANGUAGES = ("Russian",)


def _output_language(project: dict) -> str:
    """The language the edited video is spoken in: the chosen output
    language when it differs from the video's own, otherwise the video's."""
    return project.get("output_language") or project.get("language", "")


def _is_translating(project: dict) -> bool:
    output = project.get("output_language")
    return bool(output) and output != project.get("language")


def _write_project_settings(project: dict) -> None:
    video_language = project.get("language") or "unknown"
    if _is_translating(project):
        output_line = (
            f"Output language: {project['output_language']} — TRANSLATE: everything you write "
            f"(outline titles and text, new parts) is in {project['output_language']}"
        )
    else:
        output_line = f"Output language: {video_language} (same as the video, no translation)"
    PROJECT_SETTINGS_PATH.write_text(
        "\n".join([
            "# Project settings (written by the app — read only, do not edit)",
            "",
            f"Work type: {project['work_type']} — {WORK_TYPES[project['work_type']]}",
            f"Video language: {video_language}",
            output_line,
            "",
        ]),
        encoding="utf-8",
    )


def _public_settings(project: dict) -> dict:
    return {
        "work_type": project.get("work_type"),
        "output_language": project.get("output_language") or "",
        "video_language": project.get("language", ""),
        "translating": _is_translating(project),
        "outline_saved": _has_saved_outline(),
    }


@app.post("/api/project/settings")
async def project_settings(
    project_id: str = Form(...), work_type: str = Form(...), output_language: str = Form("")
):
    """Step 2: the kind of video to make and the language it's spoken in.
    Written to workspace/project.md so Claude follows it in every mode."""
    project = _get_project(project_id)
    if work_type not in WORK_TYPES:
        raise HTTPException(400, f"Unknown work type: {work_type}")
    if output_language and output_language not in OUTPUT_LANGUAGES:
        raise HTTPException(400, f"Can't translate into {output_language} yet.")

    # "Same as the video" is stored as "", also when the same language is picked.
    if output_language == project.get("language"):
        output_language = ""
    project["work_type"] = work_type
    project["output_language"] = output_language
    _write_project_settings(project)

    # A new output language needs its own outline: keep the current one
    # under its old language, and bring back one saved for the new language.
    new_language = _output_language(project)
    previous_language = _read_source().get("output_language")
    if previous_language and previous_language != new_language:
        _save_outline_to_cache()
        OUTLINE_PATH.unlink(missing_ok=True)
        PAUSES_PATH.unlink(missing_ok=True)
    _write_source(output_language=new_language)
    restored = _restore_outline_from_cache()
    return {**_public_settings(project), "outline_restored": restored}


@app.get("/api/project/{project_id}/settings")
async def get_project_settings(project_id: str):
    return _public_settings(_get_project(project_id))


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
        ],
        "saved": _save_outline_to_cache(),
    }


@app.post("/api/outline/delete")
async def delete_outline():
    """"Delete outline" in the app: forget the saved outline for this video
    and language, and the workspace copy, so Claude is asked for a new one."""
    target = _outline_cache_dir()
    if target is not None:
        shutil.rmtree(target, ignore_errors=True)
    OUTLINE_PATH.unlink(missing_ok=True)
    PAUSES_PATH.unlink(missing_ok=True)
    return {"deleted": True}


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

    SCRIPT_PATH.write_text(build_script(chunks, _output_language(project)), encoding="utf-8")
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

    prefix = _PIPER_PREFIX_BY_LANGUAGE.get(_output_language(project))
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
    return _synthesize_to(CHUNK_AUDIO_DIR / f"chunk_{index:04d}", text, voice, rate)


def _synthesize_to(base: Path, text: str, voice: str, rate: float) -> Path:
    """Voices `text` to `base` + .wav (Piper) or .mp3 (Azure)."""
    if voice in PIPER_KNOWN_VOICES:
        audio_path = base.with_suffix(".wav")
        synthesize_to_wav(text, voice, str(audio_path), rate=rate)
    elif voice in azure_tts.KNOWN_VOICES:
        audio_path = base.with_suffix(".mp3")
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


# --- The author's own parts in a review: host voice + music ----------------
#
# Saved background tracks for the added parts live in media/music/ and are
# reused across projects; selected.txt remembers the last one picked.
MUSIC_DIR = MEDIA_DIR / "music"
MUSIC_SELECTED_PATH = MUSIC_DIR / "selected.txt"
MUSIC_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")
HOST_MUSIC_DEFAULT_DB = -22.0


def _music_tracks() -> list[str]:
    if not MUSIC_DIR.exists():
        return []
    return sorted(
        (p.name for p in MUSIC_DIR.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS),
        key=str.lower,
    )


def _music_track_path(name: str) -> Path:
    path = MUSIC_DIR / Path(name).name
    if not name or path.name != name or not path.is_file() or path.suffix.lower() not in MUSIC_EXTENSIONS:
        raise HTTPException(404, f"No saved music track named {name!r}.")
    return path


def _selected_music() -> str:
    if not MUSIC_SELECTED_PATH.exists():
        return ""
    name = MUSIC_SELECTED_PATH.read_text(encoding="utf-8").strip()
    return name if name in _music_tracks() else ""


def _select_music(name: str) -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    MUSIC_SELECTED_PATH.write_text(name, encoding="utf-8")


def _host_settings(host_voice: bool, host_music: str, host_music_db: float) -> dict:
    """How the added parts sound: `host_voice` applies render.HOST_VOICE_FILTER
    to their voice-over, `host_music` is a saved track ("" for none) played
    under each of them at `host_music_db`. The track choice is remembered."""
    music_path = str(_music_track_path(host_music)) if host_music else None
    _select_music(host_music)
    return {"voice": host_voice, "music_path": music_path, "music_db": host_music_db}


def _host_render_args(layout: "VoiceLayout", host: dict) -> dict:
    return {
        "host_overlays": layout.host_overlays,
        "host_voice": bool(host.get("voice")),
        "host_music": layout.host_spans,
        "host_music_path": host.get("music_path"),
        "host_music_db": host.get("music_db", HOST_MUSIC_DEFAULT_DB),
    }


@app.get("/api/music")
def list_music():
    return {"tracks": _music_tracks(), "selected": _selected_music(), "default_db": HOST_MUSIC_DEFAULT_DB}


@app.post("/api/music")
async def upload_music(music: UploadFile = File(...)):
    """Saves a track for the added parts (kept for later projects) and
    selects it."""
    name = Path(music.filename or "").name.strip()
    if not name or Path(name).suffix.lower() not in MUSIC_EXTENSIONS:
        raise HTTPException(400, f"Pick an audio file ({', '.join(MUSIC_EXTENSIONS)}).")
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    with open(MUSIC_DIR / name, "wb") as f:
        while data := await music.read(1024 * 1024):
            f.write(data)
    _select_music(name)
    return list_music()


@app.get("/api/music/file/{name}")
def music_file(name: str):
    return FileResponse(_music_track_path(name))


@app.post("/api/music/delete")
def delete_music(name: str = Form(...)):
    _music_track_path(name).unlink()
    return list_music()


@dataclass
class VoiceLayout:
    overlays: list[tuple[float, str]]          # voice-over of the kept chunks
    host_overlays: list[tuple[float, str]]     # voice-over of the added parts
    inserts: list[tuple[float, float]]         # (anchor, duration) per added part
    insert_clips: list[list[tuple[str, float, float]]]
    host_spans: list[tuple[float, float]]      # (output start, duration) per added part


def _voice_layout(
    project: dict,
    entries: list[tuple[str, float, Path | None, int]],
    keep_segments: list[tuple[float, float]],
) -> VoiceLayout:
    """entries: (kind, start, audio_path, addition_index) per chunk, in chunk
    order. Returns the voice overlays (output start, path) — the added
    parts' ones separately — the inserts (anchor, duration), each insert's
    picked footage (see broll.py) and where each insert sits in the output,
    for render_video_with_audio. An added chunk only becomes an insert once it
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
    host_overlays = [
        (insert_start + INSERT_PAD_SECONDS, str(path))
        for insert_start, path in zip(timeline.insert_starts, added_audio)
    ]
    host_spans = [
        (insert_start, duration)
        for insert_start, (_, duration) in zip(timeline.insert_starts, inserts)
    ]
    return VoiceLayout(overlays, host_overlays, inserts, insert_clips, host_spans)


def _run_render_with_audio(
    project_id: str,
    keep_segments: list[tuple[float, float]],
    output_path: Path,
    keep_original_audio: bool,
    layout: VoiceLayout,
    music_path: str | None,
    music_db: float,
    host: dict,
) -> None:
    project = PROJECTS[project_id]
    try:
        render_video_with_audio(
            project["video_path"],
            str(output_path),
            keep_segments,
            keep_original_audio,
            layout.overlays,
            music_path,
            music_db,
            layout.inserts,
            layout.insert_clips,
            **_host_render_args(layout, host),
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
    host_voice: bool = Form(False),
    host_music: str = Form(""),
    host_music_db: float = Form(HOST_MUSIC_DEFAULT_DB),
):
    """Like /api/render, but with a custom audio mix: optionally drop the
    original audio track entirely, optionally loop a background music file
    under the whole video, and overlay every already-generated chunk
    voice-over (workspace/chunk_audio/) at its mapped position in the final
    timeline.

    `host_voice` / `host_music` / `host_music_db` — see _host_settings."""
    project = _get_project(project_id)
    host = _host_settings(host_voice, host_music, host_music_db)

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
    layout = VoiceLayout([], [], [], [], [])
    if project.get("vtt_text") and CHUNK_AUDIO_DIR.exists():
        chunks, _, _, _ = _build_voice_chunks(project, normalized)
        layout = _voice_layout(
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
            layout,
            music_path,
            music_db,
            host,
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

# What happens to the speaker's real voice under automatic TTS:
#   replace — removed, every chunk is voiced (the re-voice default)
#   under   — kept quieter under every voiced chunk (voice-over translation)
#   keep    — kept as it is; only the new parts are voiced (a review that
#             quotes the reviewer in his own language)
ORIGINAL_AUDIO_MODES = ("replace", "under", "keep")
# How much quieter the real voice is in "under".
ORIGINAL_UNDER_DB = -16.0
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

    text = record["text"]
    speech = pauses.strip_markers(text)
    has_markers = pauses.has_markers(text)
    record.update(pauses=0, pause_source=None)

    if force_rate is None:
        estimator = _estimator_voice(voice)
        # Pauses typed in the text (`||3`) take their seconds out of the window.
        reserved = pauses.fixed_pause_total(text)
        if estimator is None:
            # Nothing to predict with: just generate at normal speed.
            choice = duration_fit.RateChoice(1.0, 0.0, "ok")
        else:
            CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            estimate_path = CHUNK_AUDIO_DIR / _ESTIMATE_PATH_NAME
            synthesize_to_wav(speech, estimator, str(estimate_path), rate=1.0)
            duration_1x = get_duration(str(estimate_path))
            estimate_path.unlink(missing_ok=True)
            if is_azure:
                duration_1x *= _azure_correction(run)
            choice = duration_fit.choose_rate(duration_1x, window - reserved, voice if is_azure else None)

        record.update(rate=choice.rate, estimate=choice.estimate + reserved)
        if choice.verdict == "too_long":
            record["status"] = choice.verdict
            return
        # Too short: voice it in parts with pauses, and flag only the
        # silence that is still left over (see backend/pauses.py).
        if (choice.verdict == "too_short" or has_markers) and _auto_tts_with_pauses(run, record, choice.rate):
            return
        if choice.verdict != "ok":
            record["status"] = choice.verdict
            return
        rate = choice.rate
    else:
        rate = force_rate
        record.update(rate=rate, estimate=None)
        if has_markers and _auto_tts_with_pauses(run, record, rate, accept=True):
            return

    def generate(at_rate: float) -> float:
        audio_path = _synthesize_chunk(index, speech, voice, rate=at_rate)
        if is_azure:
            run["azure_chars"] += len(speech)
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

    record.update(audio_duration=audio_duration, has_audio=True, text=speech)
    record["status"] = "accepted" if force_rate is not None else verdict


_COMPOSE_SAMPLE_RATE = 24000


def _compose_parts(paths: list[Path], starts: list[float], out_path: Path) -> None:
    """One mono WAV: each part placed at its start time, silence between."""
    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_COMPOSE_SAMPLE_RATE)
        written = 0
        for path, start in zip(paths, starts):
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                 "-ar", str(_COMPOSE_SAMPLE_RATE), "-"],
                capture_output=True,
                check=True,
            ).stdout
            silence = max(0, round(start * _COMPOSE_SAMPLE_RATE) - written)
            out.writeframes(bytes(2 * silence))
            out.writeframes(pcm)
            written += silence + len(pcm) // 2


def _auto_tts_with_pauses(run: dict, record: dict, rate: float, accept: bool = False) -> bool:
    """Voice a chunk in parts with pauses between them (backend/pauses.py):
    at its `||` markers if it has any, otherwise at the AI's pause hints or
    at sentence ends. Afterwards the chunk's text shows every pause as
    `||seconds`, so the user can see and change them. Returns False when
    there's nothing to split (a single sentence)."""
    voice = run["voice"]
    is_azure = voice in azure_tts.KNOWN_VOICES
    window = record["slot_duration"]
    parts, source = pauses.split_into_parts(
        record["text"], run.get("pause_hints", []), record["start"], record["end"]
    )
    if len(parts) < 2:
        return False

    target = window - duration_fit.FIT_MARGIN_SECONDS - duration_fit.FIT_MARGIN_FRACTION * window
    keep = run["keep_segments"]
    chunk_out = map_to_output_timeline(record["start"], keep)
    offsets = [
        None if part.resume is None else map_to_output_timeline(part.resume, keep) - chunk_out for part in parts
    ]
    fixed = [part.pause for part in parts]

    CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHUNK_AUDIO_DIR / f"chunk_{record['index']:04d}.wav"
    with tempfile.TemporaryDirectory(dir=CHUNK_AUDIO_DIR) as tmp:
        paths, durations = [], []
        for number, part in enumerate(parts):
            path = _synthesize_to(Path(tmp) / f"part_{number:02d}", part.text, voice, rate)
            if is_azure:
                run["azure_chars"] += len(part.text)
            paths.append(path)
            durations.append(get_duration(str(path)))
        starts = pauses.plan_starts(durations, fixed, offsets, target, [part.preferred for part in parts])
        _compose_parts(paths, starts, out_path)

    audio_duration = get_duration(str(out_path))
    shown_text = pauses.text_with_markers(parts, starts, durations)
    record.update(
        text=shown_text,
        rate=rate,
        audio_duration=audio_duration,
        has_audio=True,
        status="accepted" if accept else duration_fit.judge_actual(audio_duration, window),
        pauses=len(pauses.MARKER_RE.findall(shown_text)),
        pause_source=source,
    )
    return True


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
        layout = _auto_tts_layout(project, run)
        original_audio = run.get("original_audio", "replace")
        render_video_with_audio(
            project["video_path"],
            str(run["output_path"]),
            run["keep_segments"],
            original_audio != "replace",
            layout.overlays,
            inserts=layout.inserts,
            insert_clips=layout.insert_clips,
            original_db=ORIGINAL_UNDER_DB if original_audio == "under" else 0.0,
            **_host_render_args(layout, run.get("host") or {}),
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
            if run.get("original_audio") == "keep" and record["kind"] != "added":
                # The speaker is heard in his own voice here: nothing to voice.
                record.update(status="ok", own_voice=True)
                continue
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
    original_audio: str = Form("replace"),
    host_voice: bool = Form(False),
    host_music: str = Form(""),
    host_music_db: float = Form(HOST_MUSIC_DEFAULT_DB),
):
    """Audio Option 2: automatic TTS. Generates every chunk's voice-over
    with an automatically chosen speed, then renders. If some chunks can't
    fit, it stops in "needs_review" (see /api/auto-tts/review).

    `original_audio` — see ORIGINAL_AUDIO_MODES; `host_voice` /
    `host_music` / `host_music_db` — see _host_settings."""
    project = _get_project(project_id)
    host = _host_settings(host_voice, host_music, host_music_db)

    if not project.get("vtt_text"):
        raise HTTPException(400, "No transcript yet for this project.")
    if voice not in PIPER_KNOWN_VOICES and voice not in azure_tts.KNOWN_VOICES:
        raise HTTPException(400, f"Unknown voice: {voice}")
    if original_audio not in ORIGINAL_AUDIO_MODES:
        raise HTTPException(400, f"Unknown original audio option: {original_audio}")
    if original_audio == "keep" and _is_translating(project):
        raise HTTPException(
            400, "The video is being translated, so the original voice can't replace the voice-over."
        )

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
        "original_audio": original_audio,
        "host": host,
        "keep_segments": keep_segments,
        "output_path": OUTPUT_DIR / f"{project_id}_edited.mp4",
        "ratios": [],
        "azure_chars": 0,
        "pause_hints": _load_pause_hints(),
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


def _load_pause_hints() -> list[pauses.PauseHint]:
    if not PAUSES_PATH.exists():
        return []
    return pauses.parse_pause_hints(PAUSES_PATH.read_text(encoding="utf-8"))


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
def auto_tts_continue(
    project_id: str = Form(...),
    host_voice: bool | None = Form(None),
    host_music: str = Form(""),
    host_music_db: float = Form(HOST_MUSIC_DEFAULT_DB),
):
    """Renders after the review. The "your parts" settings may have been
    changed meanwhile, so they're taken again when sent."""
    project, run = _get_auto_tts_run(project_id)
    if host_voice is not None:
        run["host"] = _host_settings(host_voice, host_music, host_music_db)
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
