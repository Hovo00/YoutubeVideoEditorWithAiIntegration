# VideoEditorY

Edit a video by editing its transcript text, instead of a timeline.

## Current workflow (manual AI step)

1. Download a YouTube video and its auto-generated subtitles (`.vtt`) —
   e.g. via https://www.downloadyoutubesubtitles.com/
2. Open [`AI_EDITING_INSTRUCTIONS.md`](AI_EDITING_INSTRUCTIONS.md), copy the
   whole instructions block into ChatGPT (or another AI), then add your
   `INSTRUCTION:` (what to remove) and `TRANSCRIPT:` (the VTT content).
3. Copy the AI's **full reply** (it must include the `## REMOVED` section).
4. Run this app (see below), load your video, paste the AI's reply, review
   the proposed cuts, then render.

The app never talks to an AI itself at this stage — it only parses the
`## REMOVED` timestamps out of text you paste in, normalizes/merges them,
and uses FFmpeg to cut the video. See `AI_EDITING_INSTRUCTIONS.md` for why
that format is designed to never corrupt timestamps.

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) installed and on your `PATH` (provides both
  `ffmpeg` and `ffprobe`)
  - Linux: `sudo apt install ffmpeg`
  - Windows: `choco install ffmpeg` (or download a build from ffmpeg.org and
    add its `bin/` folder to PATH)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

## Run

```bash
python run.py
```

This starts a local server and opens the app in your default browser
(`http://127.0.0.1:8000`). Everything — backend and UI — runs as one
process, so the same command works unchanged on Windows and Linux.

## How it works

```
video.mp4  +  AI reply (pasted text)
                 │
                 ▼
         parse "## REMOVED" section
                 │
                 ▼
   normalize + merge overlapping cut ranges
                 │
                 ▼
     review table (toggle individual cuts on/off)
                 │
                 ▼
            FFmpeg render
                 │
                 ▼
          edited_video.mp4
```

- `backend/parser.py` — parses VTT cues and the AI's structured reply
  (`## REMOVED` / `## EDITED_TRANSCRIPT` / `## CHANGE_LOG` / `## QUESTIONS`).
- `backend/editor.py` — clips cuts to video bounds, merges overlaps, and
  computes the segments to keep.
- `backend/render.py` — `ffprobe` duration lookup + `ffmpeg` trim/concat
  render (re-encodes, so hundreds of tiny cuts stay in sync).
- `backend/main.py` — FastAPI app serving both the API and the static
  frontend (`frontend/`).
- `run.py` — single entry point: starts the server and opens the browser.

## Planned next steps

- Parse two plain VTT files (original + edited) as an alternative to
  pasting the structured AI reply, by diffing cues.
- Word-level timestamps (via a local Whisper/WhisperX pass) for
  finer-grained cuts than whole subtitle cues.
- In-app instruction box that calls an AI API directly, once the manual
  loop above has been validated enough to trust automating it.
