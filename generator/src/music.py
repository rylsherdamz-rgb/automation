import numpy as np
import wave
from pathlib import Path
from .config import CONFIG

SAMPLE_RATE = 44100


def synth_ambient(duration: float, out_path: Path) -> Path:
    """Synthesize a soft ambient music bed (no external files or API keys).

    A slow Am-F-C-G chord progression as a warm pad with gentle attack/release
    per chord, plus a faint octave shimmer. Mixed to float32 and written as
    16-bit PCM WAV.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    audio = np.zeros(n)

    roots = [110.0, 87.31, 130.81, 98.0]   # A2 F2 C3 G2
    chord_len = 8.0
    n_chords = int(np.ceil(duration / chord_len))
    for i in range(n_chords):
        idx0 = i * int(chord_len * SAMPLE_RATE)
        idx1 = min(idx0 + int(chord_len * SAMPLE_RATE), n)
        if idx0 >= n:
            break
        tt = t[idx0:idx1] - t[idx0]
        root = roots[i % len(roots)]
        freqs = [root, root * 1.5, root * 1.25, root * 2.0]
        chord = np.zeros(idx1 - idx0)
        for f in freqs:
            chord += 0.20 * np.sin(2 * np.pi * f * tt)
            chord += 0.06 * np.sin(2 * np.pi * f * 2 * tt)
        env = np.ones_like(tt)
        atk = min(int(1.0 * SAMPLE_RATE), len(tt) - 1)
        rel = min(int(1.5 * SAMPLE_RATE), max(1, len(tt) // 2))
        if atk > 0:
            env[:atk] = np.linspace(0, 1, atk)
        if rel > 0:
            env[-rel:] *= np.linspace(1, 0, rel)
        audio[idx0:idx1] += chord * env

    audio /= float(np.max(np.abs(audio)) + 1e-9)
    pcm = (audio * 0.5 * 32767).astype(np.int16)

    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return out_path


def build(voice_duration: float, work_dir: Path) -> Path | None:
    """Return a music bed of the right length, or None if music is disabled.

    Uses the configured local music file when present, otherwise synthesizes
    an ambient pad sized to the narration plus a short tail for the fade-out.
    """
    music = CONFIG.get("music", {})
    if not music.get("enabled", False):
        return None

    tail = float(music.get("tail_seconds", 4.0))
    total = voice_duration + tail

    file = str(music.get("file") or "").strip()
    if file and Path(file).exists():
        return Path(file)

    return synth_ambient(total, work_dir / "music_bed.wav")
