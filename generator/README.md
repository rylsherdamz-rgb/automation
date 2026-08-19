# FreeFaceless

**A 100% free, self-hosted pipeline that generates and uploads faceless YouTube Shorts — with no paid subscriptions.**

Everything else funnels you into ElevenLabs, HeyGen, Pictory, or n8n Cloud. FreeFaceless runs entirely on your own machine using free API tiers and local models. No credit card. No monthly bill. No per-video cost.

```
script (Groq)  →  voiceover (edge-tts)  →  captions (faster-whisper, local)
   →  b-roll (Pexels)  →  assemble (ffmpeg)  →  upload (YouTube Data API)
```

Output: a 1080×1920, 30fps, ~55-second Short, captioned and uploaded — start to finish, unattended.

---

## Why it's different

| | FreeFaceless | Typical "AI YouTube" stack |
|---|---|---|
| Script | Groq (free tier) | ChatGPT Plus ($20/mo) |
| Voiceover | edge-tts (free) | ElevenLabs ($5–22/mo) |
| Captions | faster-whisper, runs locally (free) | Paid SaaS / per-minute |
| Stock video | Pexels API (free) | Storyblocks ($30/mo) |
| Orchestration | Python on your PC (free) | n8n Cloud / Make ($20+/mo) |
| **Monthly cost** | **₹0 / $0** | **$75–100+/mo** |
| Your data & keys | stay on your machine | spread across vendors |

> **Honest note:** this is a *production* tool, not a get-rich scheme. It automates making and posting videos. Views and revenue depend entirely on your niche, content quality, and YouTube's algorithm — no tool can promise those.

---

## Quickstart (Windows)

You need: **Python 3.11+**, **ffmpeg**, and a **Google account with a YouTube channel**.

```powershell
git clone https://github.com/nils44344/FreeFaceless.git
cd FreeFaceless

# 1. Add your free API keys
Copy-Item .env.example .env      # then edit .env (Groq + Pexels keys)

# 2. Install everything into a local virtualenv
.\setup.ps1

# 3. Authorize YouTube once (opens your browser)
.\.venv\Scripts\python -m src.authorize

# 4. Dry run — builds a video but does NOT upload
.\.venv\Scripts\python -m src.pipeline --no-upload
#    → output\<timestamp>_<topic>\final.mp4

# 5. Real run — builds AND uploads
.\.venv\Scripts\python -m src.pipeline
```

Full step-by-step (including the Google Cloud setup) is in **[docs/SETUP.md](docs/SETUP.md)**.

---

## How it works

| Stage | File | What it does |
|---|---|---|
| 1. Script | `src/script.py` | Groq (`llama-3.3-70b-versatile`) writes a hook + facts + CTA as structured JSON, avoiding topics already used. |
| 2. Voice | `src/voice.py` | edge-tts synthesizes a neural voiceover (free, no key). |
| 3. Captions | `src/captions.py` | faster-whisper transcribes the audio **locally** for word-level timing, then writes karaoke-style `.ass` captions. |
| 4. B-roll | `src/visuals.py` | Pexels Videos API pulls vertical stock clips matching each scene. |
| 5. Assemble | `src/assemble.py` | ffmpeg crops/concats clips, overlays the voiceover, and burns in the captions. |
| 6. Upload | `src/upload.py` | YouTube Data API v3 uploads the Short (immediate or scheduled). |
| Orchestrator | `src/pipeline.py` | Runs stages 1–6 end to end. |
| Comments | `src/moderate.py` | Optional: sweeps recent uploads and moderates comments with Groq. |

State (used topics, published log) lives in `state.json` so it never repeats itself.

---

## Configuration

Everything tweakable lives in `config.yaml` — niche, target length, voice, caption style, video resolution, upload privacy, tags. Change the `niche` and `audience` lines and you have a different channel; no code edits needed.

```yaml
niche: "fascinating educational facts (science, history, nature, space, human body)"
voice:
  voice: en-US-ChristopherNeural
captions:
  font: "Anton"
  words_per_caption: 3
video:
  width: 1080
  height: 1920
upload:
  privacy: "public"
```

---

## Cost

| Service | Tier used | Cost |
|---|---|---|
| Groq | Free tier | $0 (rate-limited; plenty for daily posting) |
| edge-tts | Free | $0 |
| faster-whisper | Local CPU | $0 (first run downloads a ~140MB model) |
| Pexels | Free API | $0 |
| YouTube Data API | Free quota | $0 |

> Free API tiers have rate limits. FreeFaceless is built for **one channel posting on a normal schedule**, not industrial bulk generation. If you scale up, you may hit free-tier limits.

---

## Get more out of it

- ⭐ **Star the repo** if it saved you a subscription.
- 📦 **[Premium Niche Pack](https://nilaykabariya.gumroad.com/l/wkgohx)** — 6 ready-to-run niche presets, 60+ topic ideas, hook formulas, and caption styles. Pay what you want.

---

## Credits & license

- Code: **MIT** — see [LICENSE](LICENSE). Use it, fork it, even sell what you make with it.
- Caption font: **[Anton](https://fonts.google.com/specimen/Anton)**, SIL Open Font License — see `assets/fonts/Anton-OFL.txt`.

FreeFaceless is not affiliated with YouTube, Google, Groq, or Pexels. Follow each service's Terms of Service and YouTube's policies on automated/AI content.
