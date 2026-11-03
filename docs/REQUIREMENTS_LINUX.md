# VideoEditorY — Linux setup

## 1. Python

Python 3.10 or newer — most distros already have this (`python3 --version`).

## 2. FFmpeg (video/audio cutting, rendering, and audio extraction for Whisper)

```bash
sudo apt install ffmpeg
```

Verify with:

```bash
ffmpeg -version
ffprobe -version
```

## 3. Project virtual environment + base Python packages

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

This installs FastAPI/uvicorn, `yt-dlp` (YouTube downloader), `openai-whisper`
(transcription), and `piper-tts` (local text-to-speech). `openai-whisper` pulls in a
generic `torch` by default — step 4 below replaces it with the right CUDA build for your
hardware. **Pick ONE of the two paths in step 4** depending on whether this is a normal
x86_64 machine or a Jetson board — they are not interchangeable.

## 4a. PyTorch with CUDA — generic x86_64 Linux + NVIDIA GPU

This is the common case: a regular desktop/server with a normal NVIDIA GPU (not a Jetson
board). Check your driver's supported CUDA version with `nvidia-smi` (top-right of the
output), then install a matching PyTorch build:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

(Swap `cu121` for whatever matches your driver — see the
[PyTorch install matrix](https://pytorch.org/get-started/locally/) for the exact command.)
No further configuration needed — the app auto-detects CUDA and falls back to CPU if
unavailable. If you don't have an NVIDIA GPU, skip this step; CPU transcription still
works, just slower.

## 4b. PyTorch with CUDA — Jetson (aarch64, JetPack)

**Do not use step 4a on a Jetson board** — the standard PyTorch wheels aren't built for
Jetson's architecture or iGPU. This path is validated on a Jetson Orin NX running JetPack 6
(CUDA 12.6); adjust version numbers if your JetPack version differs.

```bash
# Use a dedicated venv so none of this can affect anything else on the system.
python3 -m venv ~/whisper-venv
source ~/whisper-venv/bin/activate
pip install -r backend/requirements.txt

# Jetson-specific torch build, from NVIDIA's own Jetson AI Lab package index —
# --force-reinstall --no-deps avoids pulling in the generic (non-Jetson) torch
# dependencies openai-whisper's install already brought in above.
pip install --force-reinstall --no-deps torch==2.9.1 torchvision==0.24.1 \
  --index-url https://pypi.jetson-ai-lab.io/jp6/cu126

# cuDSS isn't part of the base JetPack CUDA toolkit — this exact version is
# required for compatibility with the torch build above.
pip install nvidia-cudss-cu12==0.8.0.10 --index-url https://pypi.jetson-ai-lab.io/jp6/cu126
```

This Jetson torch build needs two extra things on the dynamic linker's search path beyond
what's there by default:
1. The **system's own JetPack CUDA toolkit's cuBLAS**, ahead of the pip-distributed one —
   the pip-distributed `nvidia-cublas-cu12` wheel is not built for Jetson's iGPU and fails
   with `CUBLAS_STATUS_ALLOC_FAILED` at runtime.
2. The **`nvidia-cudss-cu12` package's own lib directory** (cuDSS isn't part of the base
   CUDA toolkit at all) — without it you'll see `ImportError: libcudss.so.0: cannot open
   shared object file`.

**The app itself handles this automatically** — `youtube_ingest.py` detects it's running on
a Jetson board (via `/etc/nv_tegra_release`) and builds the correct `LD_LIBRARY_PATH` for
the `whisper` subprocess on every call, dynamically locating whichever venv's `bin/whisper`
is found on `PATH` and adding that venv's own `nvidia/*/lib` directories after the system
CUDA path. **You don't need to edit anything for the app to work** — this is only relevant
if you also want to run `whisper` directly from a terminal yourself (e.g. to test). For
that, add this to `~/whisper-venv/bin/activate` (append after the existing `PATH=...`
line), scoped to just this venv:

```bash
_SITE_PACKAGES="$VIRTUAL_ENV/lib/python3.10/site-packages"
export LD_LIBRARY_PATH="/usr/local/cuda-12.6/targets/aarch64-linux/lib:$_SITE_PACKAGES/nvidia/cu12/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset _SITE_PACKAGES
```

(Adjust `cuda-12.6` and `python3.10` to match your JetPack/Python version if different.)
Re-activate the venv (`deactivate` then `source ~/whisper-venv/bin/activate`) after editing
it.

Verify CUDA is actually being used:

```bash
python3 -c "import torch; print(torch.cuda.is_available())"
```

If this still fails, double-check the `nvidia-cudss-cu12` version pin above — a mismatched
version produces the same `libcudss.so.0` import error.

## 4c. Making the app actually find this venv's `whisper` (Jetson only)

**This step is the one most likely to get skipped, and the app won't work without it.**
The main app (started in step 3's `.venv`) and the GPU-correct `whisper` binary (installed
in the separate `~/whisper-venv` in step 4b) are now two different venvs. `youtube_ingest.py`
finds `whisper` by searching `PATH` at the moment it needs to run it — it does **not** know
about `~/whisper-venv` unless you put it on `PATH` yourself, every time, **before** starting
the app:

```bash
source .venv/bin/activate
export PATH="$HOME/whisper-venv/bin:$PATH"
python run.py
```

The `export PATH=...` line must come **after** activating `.venv` (so it ends up first,
taking priority over anything `.venv/bin` might also provide) and **before** `python run.py`.
Without it, either you'll see `Whisper is not installed` (if `.venv` has no `whisper` at
all), or a non-GPU/potentially broken `whisper` will silently run instead (if `.venv`'s own
`openai-whisper` install shadows the correct one). Add the `export PATH=...` line to your
`~/.bashrc` (after wherever you normally activate `.venv`) so you don't have to retype it
every session.

**Optional:** `WHISPER_MODEL_SIZE` env var overrides the default `small` Whisper model
(e.g. `export WHISPER_MODEL_SIZE=medium`) — set it in the same shell before `python run.py`.

## 5. Piper voice models (for text-to-speech)

Piper itself is already installed via `requirements.txt`. Voice models are downloaded
separately into `tts_voices/`:

```bash
python3 -m piper.download_voices en_US-ryan-medium --data-dir tts_voices
```

Swap the voice name for any other [Piper voice](https://github.com/rhasspy/piper/blob/master/VOICES.md)
you want available in the app's voice picker — download as many as you like, each one just
needs its own `.onnx`/`.onnx.json` pair in `tts_voices/`.

## 6. Azure AI Speech (optional — paid, higher-quality TTS alternative to Piper)

Only needed if you want the Azure voice option in the TTS picker. Skip this entirely if
Piper's quality is good enough for you — it's free and offline.

```bash
export AZURE_SPEECH_KEY="your-key-here"
export AZURE_SPEECH_REGION="your-region-here"
```

Add these to your `~/.bashrc` (or equivalent) to persist across terminal sessions. Get a
key from the [Azure AI Speech](https://azure.microsoft.com/en-us/products/ai-services/ai-speech)
resource in the Azure portal — the free tier covers 500,000 characters/month.

## 7. Run the app

```bash
python run.py
```

**On Jetson, don't skip step 4c above** — `python run.py` alone won't find the GPU-correct
`whisper` binary unless you've exported `PATH` to include `~/whisper-venv/bin` first.

Opens automatically at `http://127.0.0.1:8000`. On a headless/SSH session where a browser
can't open automatically, just navigate to that URL yourself.
