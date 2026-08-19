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
| **Generator** | `generator/` (FreeFaceless) | AI script → edge-tts voiceover → word-timed captions (local Whisper) → Pexels b-roll → ffmpeg assembly with a background music bed | `generator/output/<ts>_<topic>/final.mp4` |
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
  ```
- `clipper/.env`:
  ```
  NVIDIA_API_KEY=nvapi-...
  LLM_PROVIDER=nvidia
  ```

| Service | Where to get it | Cost |
|---|---|---|
| NVIDIA NIM | https://build.nvidia.com → API keys | Free (rate-limited) |
| Pexels | https://www.pexels.com/api/ | Free |
| edge-tts (voice) | built-in | Free |
| Whisper (captions) | local, downloaded once (~140 MB) | Free |

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

Three tabs:

- **Generator** — set niche / audience / length / voice / music, press *Generate
  Video*. Watch every stage stream into the console. The full script is always
  spoken — the last scene is padded so nothing gets cut, and a synthesized
  ambient music bed is mixed under the narration (tunable volume).
- **Clipper** — paste a YouTube URL or pick a local file, choose clip count,
  aspect ratio (9:16 for Shorts/Reels), and a **minimum clip length** so shorts
  are never too short. Press *Clip Video*.
- **Guide** — the step-by-step reference below, in-app.

Both pipelines run independently and can be started at the same time. Errors
appear in red; stop any run with the red *Stop* button.

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
| `voice.voice` | `en-US-ChristopherNeural` | Any edge-tts voice |
| `music.enabled` | `true` | Mixes ambient bed under narration |
| `music.volume` | `0.15` | 0.05–0.30 feels best under voice |
| `music.file` | `""` | Set to a local mp3/wav to use your own track |
| `captions.whisper_model` | `base` | `tiny/base/small/medium/large-v3` |
| `video.width/height` | `1080×1920` | Vertical 9:16 |

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
| Pexels download times out | Flaky network — retries are built in; re-run |
| NVIDIA call is slow (1–2 min) | Normal for free NIM tier; it's queued |
| `[WinError 32]` in clipper | OpenCV pinned to `<5`; if you reinstall, keep it there |
| Clips are too short | Raise `LOCAL_MIN_CLIP_DURATION` (e.g. `45`) |
| `GROQ_API_KEY` errors | Keys are now `LLM_API_KEY` (NVIDIA); see `generator/.env` |

---

## Notes

- Both sub-projects are MIT-licensed upstream; this repository adds the NVIDIA
  integration, background music, minimum-clip enforcement, Windows fixes, and
  the GUI on top.
- Follow each service's ToS and YouTube's policies on AI/automated content.
- Rotate API keys if they're ever shared outside this machine.
