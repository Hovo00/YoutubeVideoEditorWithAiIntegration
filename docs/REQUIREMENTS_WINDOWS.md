# VideoEditorY — Windows setup

## 1. Python

Python 3.10 or newer, from [python.org](https://www.python.org/downloads/windows/)
or the Microsoft Store. Check "Add python.exe to PATH" during install.

## 2. FFmpeg (video/audio cutting, rendering, and audio extraction for Whisper)

```powershell
choco install ffmpeg
```

Or download a build from [ffmpeg.org](https://ffmpeg.org/download.html#build-windows)
and add its `bin\` folder to your PATH. Verify with:

```powershell
ffmpeg -version
ffprobe -version
```

## 3. Project virtual environment + base Python packages

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
```

This installs FastAPI/uvicorn, `yt-dlp` (YouTube downloader), `openai-whisper`
(transcription), and `piper-tts` (local text-to-speech). `openai-whisper` pulls in a
generic CPU-only `torch` by default — step 4 below replaces it with a CUDA build if you
have an NVIDIA GPU.

## 4. PyTorch with CUDA (optional, but strongly recommended if you have an NVIDIA GPU)

Transcription runs on CPU by default, which works but is slow for longer videos. If you
have an NVIDIA GPU, install a CUDA-enabled PyTorch build matching your installed CUDA
toolkit version (check with `nvidia-smi` — the "CUDA Version" in the top-right is the
newest toolkit your driver supports):

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

(Swap `cu121` for whatever CUDA version matches your driver — see the
[PyTorch install matrix](https://pytorch.org/get-started/locally/) for the exact command.)
No further configuration is needed — `whisper` (installed into this same `.venv` in step 3)
auto-detects CUDA and falls back to CPU if unavailable or broken, since everything lives in
one virtual environment on Windows (unlike the Jetson/Linux setup, which needs a second,
separately-tuned venv — see the Linux doc if that ever applies to you).

If you don't have an NVIDIA GPU, skip this step entirely; CPU transcription still works.

**Optional:** `WHISPER_MODEL_SIZE` env var overrides the default `small` Whisper model
(e.g. `setx WHISPER_MODEL_SIZE medium`, then open a new terminal) if you want a larger/more
accurate (but slower) model.

## 5. Piper voice models (for text-to-speech)

Piper itself is already installed via `requirements.txt`. Voice models are downloaded
separately into `tts_voices\`:

```powershell
python -m piper.download_voices en_US-ryan-medium --data-dir tts_voices
```

Swap the voice name for any other [Piper voice](https://github.com/rhasspy/piper/blob/master/VOICES.md)
you want available in the app's voice picker — download as many as you like, each one just
needs its own `.onnx`/`.onnx.json` pair in `tts_voices\`.

## 6. Azure AI Speech (optional — paid, higher-quality TTS alternative to Piper)

Only needed if you want the Azure voice option in the TTS picker. Skip this entirely if
Piper's quality is good enough for you — it's free and offline.

```powershell
setx AZURE_SPEECH_KEY "your-key-here"
setx AZURE_SPEECH_REGION "your-region-here"
```

(Open a new terminal after `setx` for it to take effect.) Get a key from the
[Azure AI Speech](https://azure.microsoft.com/en-us/products/ai-services/ai-speech)
resource in the Azure portal — the free tier covers 500,000 characters/month.

## 7. Run the app

```powershell
python run.py
```

Opens automatically at `http://127.0.0.1:8000`.

## GPU video encoding (NVENC, optional)

Rendering uses the NVIDIA hardware encoder automatically when it works, and falls back
to CPU x264 otherwise. Recent FFmpeg builds need a recent NVIDIA driver for NVENC
(FFmpeg 9 needs driver 610+, FFmpeg 7.1 needs 570+), which older cards such as the
GTX 10-series may not get. In that case download an older build, e.g. gyan's
[FFmpeg 7.0.2 essentials](https://github.com/GyanD/codexffmpeg/releases/tag/7.0.2),
and point the app at it for rendering only:

```powershell
setx FFMPEG_RENDER_PATH "D:\Tools\ffmpeg-7.0\bin\ffmpeg.exe"
```

(Open a new terminal afterwards.) The FFmpeg on PATH is still used for everything else.
