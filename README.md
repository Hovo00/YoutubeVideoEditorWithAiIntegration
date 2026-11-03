# VideoEditorY

Edit a video by editing its transcript text, instead of a timeline.

## Current workflow

1. Paste a YouTube URL into the app and pick the spoken language. The app downloads the
   video and transcribes it locally with Whisper — no manual caption download/upload.
2. Choose one of three editing modes:
   - **Manual** — every Whisper cue shown with its timestamp; check the ones to remove,
     no AI involved.
   - **AI outline** — copy a prompt into Claude Desktop/Code; it structures the transcript
     into titled paragraphs (correcting Whisper mis-transcriptions as it goes, per
     [`AI_EDITING_INSTRUCTIONS.md`](AI_EDITING_INSTRUCTIONS.md)) and writes
     `workspace/outline.md`. Load it, check sections to remove.
   - **AI autonomous** — describe the result you want (e.g. "trim this 40-minute video to
     about 15 minutes, keep only the important information"); copy the prompt into Claude,
     which decides what to cut and writes `workspace/cuts.md`. Load it.
3. Review the resulting cuts (toggle any on/off), then choose one of three audio modes:
   - **Original audio** — just cut, keep the real audio.
   - **Automatic TTS** — generates a Piper voice-over for every chunk automatically (a
     minimal first version; to be improved later).
   - **Manual TTS** — review/edit/generate or upload a voice-over per chunk yourself.
4. Render and download.

The app never talks to an AI itself — the AI steps are copy-paste into Claude Desktop/Code
(or any other AI chat), and the app only parses the resulting `outline.md`/`cuts.md` files
or pasted text, normalizes/merges the cuts, and uses FFmpeg to cut the video. See
`AI_EDITING_INSTRUCTIONS.md` for why that format is designed to never corrupt timestamps.

## Requirements

Setup differs enough between platforms (especially CUDA/PyTorch for Whisper) that it has
its own document per OS:

- [Windows setup](docs/REQUIREMENTS_WINDOWS.md)
- [Linux setup](docs/REQUIREMENTS_LINUX.md) (covers both generic x86_64+NVIDIA and
  Jetson/aarch64)

## Run

```bash
python run.py
```

This starts a local server and opens the app in your default browser
(`http://127.0.0.1:8000`). Everything — backend and UI — runs as one
process, so the same command works unchanged on Windows and Linux.

## How it works

```
YouTube URL
     │
     ▼
yt-dlp download + Whisper transcription (background job, polled)
     │
     ▼
   pick an editing mode (manual / AI outline / AI autonomous)
     │
     ▼
   normalize + merge overlapping cut ranges
     │
     ▼
     review table (toggle individual cuts on/off)
     │
     ▼
   pick an audio mode (original / automatic TTS / manual TTS)
     │
     ▼
            FFmpeg render
                 │
                 ▼
          edited_video.mp4
```

- `backend/youtube_ingest.py` — yt-dlp download, audio extraction, and Whisper
  transcription (all subprocess-based).
- `backend/parser.py` — parses VTT cues, the outline format, and the AI's structured
  `## REMOVED` reply.
- `backend/chunker.py` — splits the surviving transcript into voice-over chunks, one per
  outline paragraph/sub-paragraph (using the AI outline's own, possibly corrected, text) or
  falling back to ~500-character chunks.
- `backend/editor.py` — clips cuts to video bounds, merges overlaps, and computes the
  segments to keep.
- `backend/render.py` — `ffprobe` duration lookup + `ffmpeg` trim/concat render (re-encodes,
  so hundreds of tiny cuts stay in sync), plus the custom-audio-mix render used by the TTS
  audio modes.
- `backend/tts.py` / `backend/azure_tts.py` — Piper (local, free) and Azure AI Speech
  (cloud, paid) text-to-speech backends.
- `backend/main.py` — FastAPI app serving both the API and the static frontend
  (`frontend/`).
- `run.py` — single entry point: starts the server and opens the browser.
