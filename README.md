# VideoEditorY

Edit a video by editing its transcript text, instead of a timeline.

## Current workflow

1. Paste a YouTube URL into the app and pick the spoken language. The app downloads the
   video and transcribes it locally with Whisper — no manual caption download/upload.
2. Choose what to make, and in which language (saved to `workspace/project.md`, which
   Claude reads in every mode):
   - **Re-voice edit** — cut the video and voice it (bloopers + TTS).
   - **Review of a review** — the video is someone else's review: keep the parts worth
     quoting, and Claude writes your own review around them.
   - **Output language** — the video's own, or **Russian**: Claude then writes the outline
     and every new part in Russian, and the video is voiced in Russian.
3. Choose one of three editing modes:
   - **Manual** — every Whisper cue shown with its timestamp; check the ones to remove,
     no AI involved. Not available when translating.
   - **AI outline** — copy a prompt into Claude Desktop/Code; it structures the transcript
     into titled paragraphs (correcting Whisper mis-transcriptions as it goes, and
     translating when asked, per [`AI_EDITING_INSTRUCTIONS.md`](AI_EDITING_INSTRUCTIONS.md))
     and writes `workspace/outline.md`. Load it, check sections to remove.
     Every loaded outline is saved with the video (per output language), so opening the
     same video again brings it back without asking Claude; "Delete outline" forgets it.
   - **AI autonomous** — describe the result you want (e.g. "trim this 40-minute video to
     about 15 minutes, keep only the important information"); copy the prompt into Claude,
     which decides what to cut and writes `workspace/cuts.md`. Load it.
4. Review the resulting cuts (toggle any on/off).
5. Add new spoken parts — optional for a re-voice edit (intro, outro, news… — Mode 4), and
   required for a review (Claude introduces the reviewer's parts as quotes and reacts to
   them — Mode 5). Both are written to `workspace/additions.md`.
6. Pick the footage shown while each new part is spoken: clips from the main video or from
   other YouTube links.
7. Choose an audio mode:
   - **Original audio** — just cut, keep the real audio (re-voice edits without
     translation only).
   - **Automatic TTS** — generates a Piper or Azure voice-over, picking a speed (0.9x–1.1x)
     per chunk so it fills its window. The speaker's real voice can be replaced, kept
     quieter underneath (voice-over translation), or kept as it is with only the new parts
     voiced (a review in the video's own language). Each chunk is first measured with a free
     Piper voice, so chunks that can't fit are listed for you to edit or accept before
     rendering, and never sent to Azure.
   - **Manual TTS** — review/edit/generate or upload a voice-over per chunk yourself.

   In a review, **Your parts** sets how your own commentary sounds so it stands out
   from the quotes: +2 dB louder, slightly deeper and a warmer "studio" sound, plus an
   optional music track under every part (the same snippet each time, fading in and
   out). Tracks you add are saved in `media/music/` for later projects; you can
   switch tracks or delete them in the app.
8. Render and download.

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
  (cloud, paid) text-to-speech backends. `backend/duration_fit.py` picks the automatic
  TTS speed. Piper voices are calibrated so 1.0x lasts as long as Azure Dmitry at 1.0x
  (`tts_calibration.json`; regenerate with `.venv/bin/python scripts/calibrate_tts.py`,
  which spends ~5,250 Azure characters).
- `backend/main.py` — FastAPI app serving both the API and the static frontend
  (`frontend/`).
- `run.py` — single entry point: starts the server and opens the browser.
