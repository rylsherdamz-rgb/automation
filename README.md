# Faceless YouTube Automation Studio

Automate a faceless YouTube channel end-to-end with two Python pipelines plus a
single tkinter GUI to drive both:

```
┌─────────────────────────────── GUI (gui.py) ───────────────────────────────┐
│  Tab 1: Generator                     Tab 2: Clipper                        │
│  topic → script → voice → captions    long video → ranked vertical shorts   │
│  → b-roll → video (+ music)           → captioned 9:16 mp4s                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Pipeline | Repo | What it does | Output |
|---|---|---|---|
| **Generator** | `generator/` (FreeFaceless) | AI script → voiceover (edge-tts w/ offline fallback) → word-timed captions (local Whisper) → Pexels b-roll (offline fallback) → ffmpeg assembly with a background music bed | `generator/output/<ts>_<topic>/final.mp4` |
| **Clipper** | `clipper/` (AI-Youtube-Shorts-Generator) | Whisper transcript → LLM virality ranking → face-tracked 9:16 crop → captioned shorts | `clipper/output/short_0N.mp4` |

Everything runs on free tiers. No subscriptions, no watermarks.

---

## Quick Start

### 1. Prerequisites

- **ffmpeg** (required by both pipelines):
  ```
  winget install Gyan.FFmpeg
  ```
- **uv** (Python project manager): <https://docs.astral.sh/uv/>
- A **YouTube channel** with a Google account (only needed if you upload).

### 2. API keys

Both apps are wired to **NVIDIA NIM** (OpenAI-compatible) for all LLM calls —
one key covers script generation, comment moderation, and highlight ranking.

Create a `.env` in each project (templates already copied in):

- `generator/.env`:
  ```
  LLM_API_KEY=nvapi-...
  LLM_BASE_URL=https://integrate.api.nvidia.com/v1
  PEXELS_API_KEY=...
  ELEVENLABS_API_KEY=sk_...   # optional premium voice (2nd fallback key: ELEVENLABS_API_KEY2)
  ```
- `clipper/.env`:
  ```
  NVIDIA_API_KEY=nvapi-...
  LLM_PROVIDER=nvidia
  ```

| Service | Where to get it | Cost |
|---|---|---|
| NVIDIA NIM (default LLM) | https://build.nvidia.com → API keys | Free (rate-limited, can queue 1–3 min) |
| Pexels | https://www.pexels.com/api/ | Free |
| edge-tts (voice) | built-in | Free |
| Whisper (captions) | local, downloaded once (~140 MB) | Free |

**LLM provider** — the generator defaults to NVIDIA NIM only. To use a fast
alternative such as DeepSeek, add your key and pin it:

```
# generator/.env
DEEPSEEK_API_KEY=sk-...          # from https://platform.deepseek.com
DEEPSEEK_MODEL=deepseek-chat     # or deepseek-reasoner
LLM_PROVIDER=deepseek            # pin one provider: primary | xai | groq | deepseek
LLM_TIMEOUT=180                  # seconds before giving up on one provider
```

`LLM_PROVIDER=all` tries NVIDIA first, then whichever of xAI/Groq/DeepSeek have
keys, as fallbacks.

> **Never commit `.env`.** Both sub-projects ignore it.

### 3. Install dependencies (once)

```
cd generator && uv venv && uv pip install -r requirements.txt
cd ../clipper && uv venv && uv pip install -r requirements.txt -r requirements-local.txt
```

### 4. Launch the GUI

```
uv run gui.py
```

(Equivalent, using the generator's virtualenv directly:
`generator\.venv\Scripts\python.exe gui.py`)

Three views (sidebar navigation):

- **Create Video** — set niche / audience / length / voice / music, press *Generate
  Video*. Watch live **% progress** per stage (script → voice → captions →
  b-roll → assembly), with a status pill, elapsed time, and a clickable
  **Output History** of every finished video (open / copy path / open folder).
  The full script is always spoken — the last scene is padded so nothing gets
  cut, and a synthesized ambient music bed is mixed under the narration.
- **Clip to Shorts** — paste a YouTube URL or pick a local file, choose clip
  count, aspect ratio (9:16 for Shorts/Reels), and a **minimum clip length** so
  shorts are never too short. Live % progress across download → transcript →
  highlight ranking → rendering, plus a shorts **history list** grouped by
  output folder.
- **Guide** — the step-by-step reference below, in-app.

Both pipelines run independently and can be started at the same time. Runs end
in three clearly signalled states — **Done** (green), **Failed** (red, keeps the
last error), or **Stopped** (amber) — so a failed run never looks like success.
Every run writes a timestamped log to `logs/` (open it with the *View Run Log*
button on each tab) — every line the pipeline printed, including any error.

A bottom **status bar** runs an environment doctor at startup: it checks
ffmpeg, both venvs, and the API keys in `generator/.env` / `clipper/.env`, so
missing setup is visible before you press run. Every GUI setting (niche,
length, voice, music, upload toggle, publish time, clip source, aspect, min
length, output folder) is remembered in `gui_state.json` between sessions.

---

## Step-by-step workflow

### A. Generate a faceless video

1. In the **Generator** tab set your `Niche` and `Audience`
   (e.g. `Japanese culture (history, food, traditions, festivals)`).
2. Choose target length (30–180 s), narrator voice, and background-music volume.
3. Press **Generate Video**. The pipeline runs:
   ```
   script (NVIDIA llama-3.3-70b) → voiceover (edge-tts)
   → word-timed captions (local faster-whisper)
   → b-roll (Pexels, vertical clips)
   → ffmpeg assembly + music bed + burned-in karaoke captions
   ```
4. Result lands in `generator/output/<timestamp>_<topic>/final.mp4`.

### B. Upload to YouTube (optional)

Do this once to authorize the app:

```
generator\.venv\Scripts\python.exe -m src.authorize
```

Then tick **Upload to YouTube** in the GUI. See `generator/docs/SETUP.md` for
the full Google Cloud console setup.

### C. Chop a long video into Shorts

1. In the **Clipper** tab, drop a YouTube URL or local `.mp4` path.
2. Set clip count, aspect ratio, and minimum clip length.
3. Press **Clip Video**:
   ```
   download/read → faster-whisper transcript → NVIDIA ranks highlights
   → dedupe + min-length expansion → face-tracked 9:16 crop → captions
   ```
4. Shorts appear as `clipper/output/short_01.mp4`, `short_02.mp4`, ...

---

## Configuration reference

### Generator — `generator/config.yaml`

| Key | Default | Notes |
|---|---|---|
| `niche` / `audience` | Japan culture | Edit via GUI or here |
| `script.target_seconds` | `120` | Video length; max `180` for Shorts |
| `script.model` | `meta/llama-3.3-70b-instruct` | Any NVIDIA NIM model |
| `voice.voice` | `en-US-ChristopherNeural` | Any edge-tts voice (or a Windows SAPI5 voice name) |
| `voice.engine` | `auto` | `auto` (edge → elevenlabs → piper → sapi5) / `edge` / `elevenlabs` / `piper` / `sapi5` |
| `voice.eleven_voice` | `Karlo` | ElevenLabs voice name or ID (premium TTS) |
| `voice.eleven_model` | `eleven_flash_v2_5` | ElevenLabs model; `eleven_multilingual_v2` is higher quality, slower |
| `voice.sapi_voice` | `""` | Optional Windows voice name/ID for the offline SAPI5 engine |
| `voice.piper_model` | `""` | Path to a `.onnx` Piper model for offline neural quality |
| `music.enabled` | `true` | Mixes ambient bed under narration |
| `music.volume` | `0.15` | 0.05–0.30 feels best under voice |
| `music.file` | `""` | Set to a local mp3/wav to use your own track |
| `captions.whisper_model` | `base` | `tiny/base/small/medium/large-v3` |
| `video.width/height` | `1080×1920` | Vertical 9:16 |
| `video.encoder` | `auto` | `auto` (uses NVIDIA NVENC when a GPU is present) / `nvenc` / `libx264` |

### Clipper — `clipper/.env`

| Env var | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `nvidia` | `openai`, `gemini`, or `nvidia` |
| `NVIDIA_MODEL` | `meta/llama-3.3-70b-instruct` | Highlight ranking model |
| `LOCAL_MIN_CLIP_DURATION` | `30` | Shorts shorter than this are expanded |
| `LOCAL_WHISPER_MODEL` | `base` | Transcription model |
| `LOCAL_OUTPUT_DIR` | `output` | Where shorts are written |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg: command not found` | `winget install Gyan.FFmpeg`, restart terminal |
| Pexels download times out | The API is slow from some networks — each scene has a hard budget, then falls back to an animated offline background so the video still builds |
| NVIDIA call is slow (1–2 min) | Normal for free NIM tier; it's queued |
| `[WinError 32]` in clipper | OpenCV pinned to `<5`; if you reinstall, keep it there |
| Clips are too short | Raise `LOCAL_MIN_CLIP_DURATION` (e.g. `45`) |
| `GROQ_API_KEY` errors | Keys are now `LLM_API_KEY` (NVIDIA); see `generator/.env` |

---

## Package as a standalone app

Turn the GUI into a Windows app you can run or share — no terminal needed.

### Option A — Single-folder app (fastest)

```
powershell -ExecutionPolicy Bypass -File build_app.ps1
```

This builds `dist/FacelessStudio.exe` (PyInstaller one-folder build), copies the
`generator/` and `clipper/` pipelines (with their venvs) next to it, generates an
app icon, and zips everything to `dist/FacelessStudio.zip`. The zip can be copied
to any Windows PC and unzipped anywhere (ffmpeg must still be installed).

### Option B — Installer

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), build the app with
Option A, then:

```
iscc installer.iss
```

This creates `dist/FacelessStudio-Setup.exe` — a real installer with Start-menu
and desktop shortcuts. **Note:** install into a user-writable folder (the default
`C:\Program Files\...` needs admin; the installer defaults to a per-user path).

### How it works

- The GUI detects when it is frozen (`sys.frozen`) and resolves the pipeline
  folders relative to the exe, so `generator/` and `clipper/` just have to sit next
  to `FacelessStudio.exe` (the build script does this for you).
- The two pipeline venvs are copied wholesale into the app folder — they are
  self-contained, so the app has everything it needs except `ffmpeg` on `PATH`.

---

## Notes

- Both sub-projects are MIT-licensed upstream; this repository adds the NVIDIA
  integration, background music, minimum-clip enforcement, Windows fixes, and
  the GUI on top.
- Follow each service's ToS and YouTube's policies on AI/automated content.
- Rotate API keys if they're ever shared outside this machine.
