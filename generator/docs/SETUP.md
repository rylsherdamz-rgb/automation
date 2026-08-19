# FreeFaceless — Full Setup Guide

This walks you through every step from a blank machine to your first uploaded Short. Budget ~30 minutes the first time. Everything here is free.

> Assumes Windows. macOS/Linux work too — just swap `winget` for `brew`/`apt` and use `python3` instead of the `.venv\Scripts\python` paths.

---

## 0. Prerequisites

### Python 3.11+
Check: `python --version`. If missing, install from <https://www.python.org/downloads/> and tick **"Add Python to PATH"** during install.

### ffmpeg
```powershell
winget install Gyan.FFmpeg
```
Close and reopen your terminal, then verify: `ffmpeg -version`.

### A YouTube channel
You need a Google account that **already has a YouTube channel**. If you don't have one, go to <https://youtube.com>, click your avatar → **Create a channel**.

---

## 1. Groq API key (script generation) — free

1. Go to <https://console.groq.com/keys>.
2. Sign in (Google login is fine).
3. Click **Create API Key**, name it `freefaceless`, and copy the key (starts with `gsk_`).
4. You'll paste it into `.env` in step 4.

No credit card required.

---

## 2. Pexels API key (stock video) — free

1. Go to <https://www.pexels.com/api/>.
2. Sign up / log in, then click **Get Started** / **Your API Key**.
3. Copy the key.

No credit card required.

---

## 3. Google Cloud — YouTube upload access

This is the only fiddly part. Do it once.

### 3a. Create a project
1. Go to <https://console.cloud.google.com/>.
2. Top bar → project dropdown → **New Project**. Name it `freefaceless` → **Create**. Make sure it's selected.

### 3b. Enable the YouTube Data API
1. Go to <https://console.cloud.google.com/apis/library/youtube.googleapis.com>.
2. Confirm your project is selected → click **Enable**.

### 3c. Configure the OAuth consent screen
1. Go to <https://console.cloud.google.com/apis/credentials/consent>.
2. User type: **External** → **Create**.
3. Fill the required fields:
   - **App name:** `FreeFaceless`
   - **User support email:** your email
   - **Developer contact email:** your email
   - Leave everything else default → **Save and Continue**.
4. **Scopes** screen → **Add or Remove Scopes** → in the filter box paste these two, tick each, then **Update**:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube.force-ssl`
   - → **Save and Continue**.
5. **Test users** screen → **Add Users** → enter the **same Google account email** that owns your YouTube channel → **Save and Continue**.
   - (You can leave the app in "Testing" mode — you don't need Google verification for your own channel.)

### 3d. Create the OAuth client (Desktop)
1. Go to <https://console.cloud.google.com/apis/credentials>.
2. **Create Credentials** → **OAuth client ID**.
3. **Application type: Desktop app**. Name it `freefaceless-desktop` → **Create**.
   - *(Desktop apps use a local loopback port, so there's no redirect URI to configure.)*
4. In the popup, click **Download JSON**.
5. Rename the downloaded file to exactly **`client_secret.json`** and move it into the **FreeFaceless project folder** (next to `setup.ps1`).

> ⚠️ **Never commit `client_secret.json` or `token.json`.** They're already in `.gitignore`. They are *your* credentials — they do not ship with the project, and you should never share them.

---

## 4. Configure and install

```powershell
cd FreeFaceless

# Create your .env from the template
Copy-Item .env.example .env
notepad .env        # paste your Groq + Pexels keys, save, close

# Install dependencies into a local virtualenv
.\setup.ps1
```

`setup.ps1` creates `.venv`, installs requirements, and warns if ffmpeg or `client_secret.json` are missing.

---

## 5. Authorize YouTube (once)

```powershell
.\.venv\Scripts\python -m src.authorize
```

- A browser window opens → choose the Google account that owns your channel.
- You'll see "Google hasn't verified this app" (expected, because it's in Testing) → **Continue** → **Allow**.
- Back in the terminal you'll see `Authorized OK. Channel: <your channel name>`.
- This writes `token.json`. **Every future run refreshes silently — no browser again.**

> Run this in **your own** terminal, not from an automated/headless context — the browser step needs you.

---

## 6. First video

```powershell
# Dry run — builds a video, does NOT upload
.\.venv\Scripts\python -m src.pipeline --no-upload
```
Open the result at `output\<timestamp>_<topic>\final.mp4` and check it looks right.

```powershell
# Real run — builds AND uploads
.\.venv\Scripts\python -m src.pipeline
```
The terminal prints the video URL when done.

To schedule instead of publishing immediately:
```powershell
.\.venv\Scripts\python -m src.pipeline --publish-at 2026-06-01T14:00:00Z
```
(ISO-8601, UTC. The video uploads as private and goes public at that time.)

---

## 7. (Optional) Post automatically every day

`run_daily.ps1` is included for use with **Windows Task Scheduler**. It has a once-per-day guard so it won't double-post.

> **Reality check:** this runs on *your* PC. It only fires while the machine is on and you're signed in — it is not a 24/7 cloud service. For always-on posting you'd need a cloud VPS (out of scope for the free setup).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `GROQ_API_KEY` KeyError | You didn't create `.env` or didn't paste the key. Re-check step 4. |
| `ffmpeg not found` | Reopen the terminal after `winget install`; confirm `ffmpeg -version`. |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Antivirus/proxy doing TLS interception. FreeFaceless already injects the Windows cert store via `truststore` in `src/config.py` — make sure `truststore` installed (it's in requirements). |
| "no YouTube channel attached" | The Google account has no channel. Create one at youtube.com, then re-run `src.authorize`. |
| Captions show a wrong/box font | Confirm `assets/fonts/Anton-Regular.ttf` exists and `config.yaml` has `font: "Anton"`. |
| First run slow at captions | faster-whisper downloads its ~140MB model once; later runs are fast. |
