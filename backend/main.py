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

from . import azure_tts, youtube_ingest
from .chunker import TextChunk, chunk_by_outline, chunk_kept_cues, kept_cues
from .editor import Cut, calculate_keep_segments, map_to_output_timeline, normalize_cuts
from .parser import ParsedResponse, parse_ai_response, parse_outline, parse_vtt
from .render import FFmpegNotFoundError, get_duration, render_video, render_video_with_audio
from .tts import KNOWN_VOICES as PIPER_KNOWN_VOICES
from .tts import VoiceNotAvailableError, list_available_voices, synthesize_to_wav

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
UPLOAD_DIR = MEDIA_DIR / "uploads"
OUTPUT_DIR = MEDIA_DIR / "outputs"
FRONTEND_DIR = BASE_DIR / "frontend"

# Fixed, predictable location mirroring the current video+VTT — so Claude
# Desktop/Claude Code can be pointed at the same path every time, regardless
# of which internal project_id is active. Holds exactly one project at a
# time (single-user tool); a new YouTube ingest overwrites whatever was here.
WORKSPACE_DIR = BASE_DIR / "workspace"
OUTLINE_PATH = WORKSPACE_DIR / "outline.md"
CUTS_PATH = WORKSPACE_DIR / "cuts.md"
CHUNK_AUDIO_DIR = WORKSPACE_DIR / "chunk_audio"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
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

    try:
        set_phase("downloading", "Downloading…", 0.0)
        video_path = youtube_ingest.download_video(
            youtube_url, project_dir, on_progress=lambda frac, msg: set_phase("downloading", msg, frac)
        )

        duration = get_duration(str(video_path))
        project["video_path"] = str(video_path)
        project["duration"] = duration

        set_phase("extracting_audio", "Extracting audio for transcription…", 0.0)
        audio_path = youtube_ingest.extract_audio(video_path, project_dir)

        vtt_text = youtube_ingest.transcribe(
            audio_path,
            language=language,
            on_progress=lambda frac, msg: set_phase("transcribing", msg, frac),
        )

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

    return _build_cuts_response(cuts, project["duration"])


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


def _cuts_response(parsed: ParsedResponse, duration: float) -> dict:
    cuts = [
        Cut(start=r.start, end=r.end, text=r.text, reason=r.reason)
        for r in parsed.removed
    ]
    return _build_cuts_response(
        cuts, duration, warnings=parsed.warnings, change_log=parsed.change_log, questions=parsed.questions
    )


@app.post("/api/parse")
async def parse_ai_text(project_id: str = Form(...), ai_response: str = Form(...)):
    project = _get_project(project_id)
    parsed = parse_ai_response(ai_response)
    return _cuts_response(parsed, project["duration"])


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

    return _build_cuts_response(cuts, project["duration"])


def _build_voice_chunks(project: dict, normalized_cuts: list[Cut]) -> tuple[list[TextChunk], int, int, str]:
    """One chunk per outline paragraph/sub-paragraph when workspace/outline.md
    exists and parses (matching whatever granularity the AI outline already
    chose), otherwise falls back to ~500-character chunks. Used both when
    generating/listing chunks and when re-deriving chunk indices at render
    time — these must stay in lockstep, or a chunk's audio could get
    matched to the wrong index."""

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

    return chunks, len(surviving_cues), len(all_cues), mode


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


def _synthesize_chunk(index: int, text: str, voice: str) -> Path:
    """Dispatches to Piper (free, offline, no API key) or Azure AI Speech
    (paid cloud API, needs AZURE_SPEECH_KEY/REGION) depending on which voice
    was picked, writing the result to workspace/chunk_audio/chunk_{index}.*"""

    CHUNK_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for old in CHUNK_AUDIO_DIR.glob(f"chunk_{index:04d}.*"):
        old.unlink()

    if voice in PIPER_KNOWN_VOICES:
        audio_path = CHUNK_AUDIO_DIR / f"chunk_{index:04d}.wav"
        synthesize_to_wav(text, voice, str(audio_path))
    elif voice in azure_tts.KNOWN_VOICES:
        audio_path = CHUNK_AUDIO_DIR / f"chunk_{index:04d}.mp3"
        azure_tts.synthesize_to_file(text, voice, str(audio_path))
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
):
    """Generate a chunk's voice-over and check it isn't longer than the
    video slot it would replace."""
    _get_project(project_id)

    try:
        audio_path = _synthesize_chunk(chunk_index, text, voice)
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
    return _cuts_response(parsed, project["duration"])


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


def _run_render_with_audio(
    project_id: str,
    keep_segments: list[tuple[float, float]],
    output_path: Path,
    keep_original_audio: bool,
    voice_overlays: list[tuple[float, str]],
    music_path: str | None,
    music_db: float,
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
    if project.get("vtt_text") and CHUNK_AUDIO_DIR.exists():
        chunks, _, _, _ = _build_voice_chunks(project, normalized)

        for index, chunk in enumerate(chunks):
            matches = [
                path
                for path in CHUNK_AUDIO_DIR.glob(f"chunk_{index:04d}.*")
                if not path.name.startswith("_music")
            ]
            if not matches:
                continue
            output_start = map_to_output_timeline(chunk.start, keep_segments)
            voice_overlays.append((output_start, str(matches[0])))

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
        ),
        daemon=True,
    )
    thread.start()

    return {"status": "started"}


def _run_auto_tts(
    project_id: str,
    normalized_cuts: list[Cut],
    keep_segments: list[tuple[float, float]],
    output_path: Path,
    voice: str,
) -> None:
    """Mode 2 of the audio-mode combobox: automatically generates a Piper/
    Azure voice-over for every surviving chunk (no per-chunk review), then
    renders straight away — i.e. the manual-TTS render path, with the
    per-chunk generation loop fully automated instead of user-driven."""

    project = PROJECTS[project_id]
    try:
        chunks, _, _, _ = _build_voice_chunks(project, normalized_cuts)
        total = len(chunks)

        for index, chunk in enumerate(chunks):
            project["status"] = "generating_voiceover"
            project["phase"] = "generating_voiceover"
            project["phase_message"] = f"Generating voice-over… chunk {index + 1}/{total}"
            project["progress"] = index / total if total else 0.0
            _synthesize_chunk(index, chunk.text, voice)

        voice_overlays: list[tuple[float, str]] = []
        for index, chunk in enumerate(chunks):
            matches = [
                path
                for path in CHUNK_AUDIO_DIR.glob(f"chunk_{index:04d}.*")
                if not path.name.startswith("_music")
            ]
            if not matches:
                continue
            output_start = map_to_output_timeline(chunk.start, keep_segments)
            voice_overlays.append((output_start, str(matches[0])))

        project["status"] = "rendering"
        project["phase"] = "rendering"
        project["phase_message"] = "Rendering video…"
        render_video_with_audio(
            project["video_path"], str(output_path), keep_segments, False, voice_overlays
        )

        project["status"] = "done"
        project["phase"] = "done"
        project["progress"] = 1.0
        project["output_path"] = str(output_path)
    except Exception as exc:
        project["status"] = "error"
        project["error"] = str(exc)


@app.post("/api/auto-tts")
async def auto_tts(
    project_id: str = Form(...),
    cuts_json: str = Form(...),
    voice: str = Form(...),
):
    """Audio Option 2 — automatic TTS: batch-generates a voice-over for
    every chunk with one default voice and no per-chunk review, then
    renders. A real but minimal first implementation, to be developed
    further later."""
    project = _get_project(project_id)

    if not project.get("vtt_text"):
        raise HTTPException(400, "No transcript yet for this project.")

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

    project["status"] = "generating_voiceover"
    project["error"] = None

    thread = threading.Thread(
        target=_run_auto_tts,
        args=(project_id, normalized, keep_segments, output_path, voice),
        daemon=True,
    )
    thread.start()

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
