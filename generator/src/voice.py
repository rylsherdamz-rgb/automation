import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import edge_tts
from .config import CONFIG

EDGE_ATTEMPTS = 2
EDGE_BUDGET = 12.0  # seconds per attempt before falling back to an offline engine


def _engine_choice() -> str:
    return str(CONFIG.get("voice", {}).get("engine", "auto")).lower()


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _to_mp3(wav: Path, mp3: Path):
    subprocess.run(
        [_ffmpeg(), "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k",
         str(mp3)],
        check=True, capture_output=True,
    )


def _eleven_keys() -> list[str]:
    k1 = os.environ.get("ELEVENLABS_API_KEY", "")
    k2 = os.environ.get("ELEVENLABS_API_KEY2", "")
    return [k for k in (k1, k2) if k]


def _eleven_synth(text: str, out_path: Path):
    """ElevenLabs (premium neural TTS, online). Uses the configured voice name/ID
    and tries both configured keys. Requires requests (already a dependency)."""
    import requests

    vcfg = CONFIG.get("voice", {})
    voice = str(vcfg.get("eleven_voice", "") or "")
    model = str(vcfg.get("eleven_model", "eleven_flash_v2_5") or "")
    if not voice:
        raise RuntimeError("elevenlabs selected but voice.eleven_voice is empty")
    keys = _eleven_keys()
    if not keys:
        raise RuntimeError("elevenlabs selected but no ELEVENLABS_API_KEY in .env")

    # Resolve a voice name (e.g. "Karlo") to its ID once, via the voices list.
    voice_id = voice
    if not voice_id.startswith(("pNInz", "21m00", "EXAVIT", "XB0fD", "onwK", "bIHBY",
                                "XrExE", "iP95p", "JBFqn", "cgSgS", "N2lS", "c9P1K",
                                "VfxnZ", "FKwA0", "ErXwO", "wsFys")):
        try:
            r = requests.get("https://api.elevenlabs.io/v1/voices",
                             headers={"xi-api-key": keys[0]}, timeout=30)
            r.raise_for_status()
            for v in r.json().get("voices", []):
                if v.get("name", "").lower() == voice.lower():
                    voice_id = v["voice_id"]
                    break
        except Exception:
            pass  # fall back to using the string as-is

    last_err: Exception | None = None
    for key in keys:
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": model,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                                       "style": 0.3},
                },
                timeout=120,
            )
            r.raise_for_status()
            out_path.write_bytes(r.content)
            if out_path.stat().st_size > 0:
                return out_path
            last_err = RuntimeError("ElevenLabs returned empty audio")
        except Exception as e:
            last_err = e
            print(f"[voice] elevenlabs key failed: {e}", flush=True)
    raise RuntimeError(f"ElevenLabs failed: {last_err}")


def _edge_synth(text: str, out_path: Path):
    """edge-tts (online, best quality). Bounded so a dead network fails fast."""
    last_err: Exception | None = None
    tmp = out_path.with_suffix(".edge.mp3")
    for attempt in range(1, EDGE_ATTEMPTS + 1):
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)

            async def _go():
                com = edge_tts.Communicate(
                    text,
                    voice=CONFIG["voice"]["voice"],
                    rate=CONFIG["voice"].get("rate", "+0%"),
                    pitch=CONFIG["voice"].get("pitch", "+0Hz"),
                )
                await com.save(str(tmp))

            asyncio.run(asyncio.wait_for(_go(), timeout=EDGE_BUDGET))

            if tmp.exists() and tmp.stat().st_size > 0:
                os.replace(tmp, out_path)
                return out_path
            last_err = RuntimeError("edge-tts returned an empty file")
        except asyncio.TimeoutError:
            last_err = RuntimeError(
                f"edge-tts timed out after {EDGE_BUDGET:.0f}s (network blocked?)")
            print(f"[voice] edge attempt {attempt}/{EDGE_ATTEMPTS}: {last_err}", flush=True)
        except Exception as e:
            last_err = e
            print(f"[voice] edge attempt {attempt}/{EDGE_ATTEMPTS} failed: {e}", flush=True)
        finally:
            tmp.unlink(missing_ok=True)
    raise RuntimeError(f"edge-tts failed: {last_err}")


def _piper_synth(text: str, out_path: Path):
    """Offline neural TTS. Needs: pip install piper-tts + a downloaded model."""
    import wave

    from piper import PiperVoice

    model = str(CONFIG.get("voice", {}).get("piper_model", "") or "")
    if not model or not Path(model).exists():
        raise RuntimeError("piper engine selected but voice.piper_model is missing")
    wav_path = out_path.with_suffix(".wav")
    voice = PiperVoice.load(model)
    with wave.open(str(wav_path), "wb") as wav:
        voice.synthesize_wav(text, wav)
    _to_mp3(wav_path, out_path)
    return out_path


def _sapi_synth(text: str, out_path: Path):
    """Offline Windows SAPI5 voices via pyttsx3 (guaranteed no network)."""
    import pyttsx3

    vcfg = CONFIG.get("voice", {})
    rate_pct = int(str(vcfg.get("rate", "-12%")).strip("%") or 0)
    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", max(80, int(200 * (1 + rate_pct / 100.0))))
        sapi_voice = str(vcfg.get("sapi_voice", "") or "")
        if sapi_voice:
            sapi_voice = sapi_voice.lower()
            for v in engine.getProperty("voices"):
                if sapi_voice in v.id.lower() or sapi_voice in v.name.lower():
                    engine.setProperty("voice", v.id)
                    break
        wav_path = out_path.with_suffix(".wav")
        engine.save_to_file(text, str(wav_path))
        engine.runAndWait()
        if not wav_path.exists() or wav_path.stat().st_size == 0:
            raise RuntimeError("SAPI produced no audio")
        _to_mp3(wav_path, out_path)
        return out_path
    finally:
        try:
            engine.stop()
        except Exception:
            pass


def synth(text: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    choice = _engine_choice()
    if choice == "edge":
        engines = ["edge"]
    elif choice == "elevenlabs":
        engines = ["elevenlabs", "sapi5"]
    elif choice == "piper":
        engines = ["piper", "sapi5"]
    elif choice == "sapi5":
        engines = ["sapi5"]
    else:  # auto: edge -> elevenlabs -> piper -> sapi5
        engines = ["edge", "elevenlabs", "piper", "sapi5"]

    errors: list[str] = []
    for eng in engines:
        try:
            if eng == "edge":
                _edge_synth(text, out_path)
            elif eng == "elevenlabs":
                _eleven_synth(text, out_path)
            elif eng == "piper":
                _piper_synth(text, out_path)
            else:
                _sapi_synth(text, out_path)
            print(f"      voiceover ready ({eng}): {out_path.stat().st_size} bytes",
                  flush=True)
            return out_path
        except Exception as e:
            errors.append(f"{eng}: {e}")
            print(f"[voice] {eng} unavailable, trying next: {e}", flush=True)

    raise RuntimeError(
        "voice synthesis failed: " + " | ".join(errors)
    )