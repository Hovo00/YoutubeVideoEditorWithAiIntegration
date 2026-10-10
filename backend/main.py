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

from .ai import ClaudeNotConfiguredError, generate_edit
from .editor import Cut, calculate_keep_segments, normalize_cuts
from .parser import ParsedResponse, parse_ai_response, parse_outline
from .render import FFmpegNotFoundError, get_duration, render_video

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "media"
UPLOAD_DIR = MEDIA_DIR / "uploads"
OUTPUT_DIR = MEDIA_DIR / "outputs"
FRONTEND_DIR = BASE_DIR / "frontend"

# Fixed, predictable location mirroring the current video+VTT — so Claude
# Desktop/Claude Code can be pointed at the same path every time, regardless
# of which internal project_id is active. Holds exactly one project at a
# time (single-user tool); a new upload overwrites whatever was here.
WORKSPACE_DIR = BASE_DIR / "workspace"
OUTLINE_PATH = WORKSPACE_DIR / "outline.md"
CUTS_PATH = WORKSPACE_DIR / "cuts.md"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VideoEditorY")

# project_id -> {video_path, duration, status, output_path, error, vtt_text, conversation}
PROJECTS: dict[str, dict] = {}


def _get_project(project_id: str) -> dict:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(404, "Unknown project_id — upload a video first.")
    return project


@app.post("/api/upload")
async def upload_video(
    video: UploadFile = File(...),
    subtitles: UploadFile | None = File(None),
):
    project_id = str(uuid.uuid4())
    project_dir = UPLOAD_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    video_path = project_dir / f"source{suffix}"

    with open(video_path, "wb") as f:
        while chunk := await video.read(1024 * 1024):
            f.write(chunk)

    try:
        duration = get_duration(str(video_path))
    except FFmpegNotFoundError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"Could not read video file: {exc}")

    vtt_text = None
    if subtitles is not None:
        vtt_bytes = await subtitles.read()
        vtt_text = vtt_bytes.decode("utf-8", errors="replace")
        (project_dir / "subtitles.vtt").write_text(vtt_text, encoding="utf-8")

    # Mirror into the fixed workspace folder (see WORKSPACE_DIR) so Claude
    # Desktop/Claude Code always has a stable path to work with. This is a
    # new "current project" — drop any previous video file (could have a
    # different extension) and any stale Step 1/Step 2 output.
    for old_video in WORKSPACE_DIR.glob("video.*"):
        old_video.unlink()
    shutil.copyfile(video_path, WORKSPACE_DIR / f"video{suffix}")
    if vtt_text is not None:
        (WORKSPACE_DIR / "subtitles.vtt").write_text(vtt_text, encoding="utf-8")
    OUTLINE_PATH.unlink(missing_ok=True)
    CUTS_PATH.unlink(missing_ok=True)

    PROJECTS[project_id] = {
        "video_path": str(video_path),
        "duration": duration,
        "status": "idle",
        "output_path": None,
        "error": None,
        "vtt_text": vtt_text,
        "conversation": [],
    }

    return {"project_id": project_id, "duration": duration, "filename": video.filename}


def _cuts_response(parsed: ParsedResponse, duration: float) -> dict:
    cuts = [
        Cut(start=r.start, end=r.end, text=r.text, reason=r.reason)
        for r in parsed.removed
    ]
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
        "warnings": parsed.warnings,
        "change_log": parsed.change_log,
        "questions": parsed.questions,
    }


@app.post("/api/parse")
async def parse_ai_text(project_id: str = Form(...), ai_response: str = Form(...)):
    project = _get_project(project_id)
    parsed = parse_ai_response(ai_response)
    return _cuts_response(parsed, project["duration"])


@app.get("/api/workspace/outline")
async def workspace_outline():
    if not OUTLINE_PATH.exists():
        raise HTTPException(404, "No outline.md yet — ask Claude to do Step 1 first.")

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


@app.get("/api/workspace/cuts")
async def workspace_cuts(project_id: str):
    project = _get_project(project_id)

    if not CUTS_PATH.exists():
        raise HTTPException(404, "No cuts.md yet — ask Claude to do Step 2 first.")

    text = CUTS_PATH.read_text(encoding="utf-8")
    parsed = parse_ai_response(text)
    return _cuts_response(parsed, project["duration"])


@app.post("/api/ai-edit")
async def ai_edit(project_id: str = Form(...), instruction: str = Form(...)):
    project = _get_project(project_id)

    if not project.get("vtt_text"):
        raise HTTPException(
            400,
            "No subtitles uploaded for this project — upload a .vtt file "
            "alongside the video to use the Claude-driven edit flow.",
        )

    try:
        reply_text, updated_messages = generate_edit(
            project["conversation"], instruction, project["vtt_text"]
        )
    except ClaudeNotConfiguredError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Claude request failed: {exc}")

    project["conversation"] = updated_messages

    parsed = parse_ai_response(reply_text)
    response = _cuts_response(parsed, project["duration"])
    response["raw_reply"] = reply_text
    return response


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


@app.get("/api/status/{project_id}")
async def status(project_id: str):
    project = _get_project(project_id)

    response = {"status": project["status"]}

    if project["status"] == "done" and project["output_path"]:
        response["download_url"] = f"/api/download/{Path(project['output_path']).name}"

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
