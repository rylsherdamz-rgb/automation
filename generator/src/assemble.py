import json
import subprocess
from pathlib import Path
from .config import CONFIG, ROOT
from . import music


def _run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        tail = (p.stderr or "")[-4000:]
        raise RuntimeError(
            f"Command failed (exit {p.returncode}): {cmd[0]} ...\n--- ffmpeg stderr ---\n{tail}"
        )


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _scene_durations(words: list[dict], scenes: list[dict]) -> list[float]:
    spoken = [s["text"].lower() for s in scenes]
    flat = [w["word"].strip().lower().strip(".,!?;:\"'") for w in words]
    durations = []
    cursor = 0
    for i, sentence in enumerate(spoken):
        scene_words = [w.strip(".,!?;:\"'") for w in sentence.split()]
        start_idx = cursor
        end_idx = min(cursor + len(scene_words), len(words))
        if i == len(spoken) - 1:
            end_idx = len(words)
        start_t = words[start_idx]["start"] if start_idx < len(words) else words[-1]["end"]
        end_t = words[end_idx - 1]["end"] if end_idx > 0 else start_t
        durations.append(max(0.5, end_t - start_t))
        cursor = end_idx
    return durations


def _prep_scene_clip(src: Path, target_dur: float, out_path: Path, w: int, h: int, fps: int):
    src_dur = probe_duration(src)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,fps={fps}"
    )
    if src_dur >= target_dur:
        _run([
            "ffmpeg", "-y", "-ss", "0", "-t", f"{target_dur:.3f}", "-i", str(src),
            "-vf", vf, "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out_path),
        ])
    else:
        loops = int(target_dur // src_dur) + 1
        _run([
            "ffmpeg", "-y", "-stream_loop", str(loops), "-i", str(src),
            "-t", f"{target_dur:.3f}", "-vf", vf, "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out_path),
        ])


def _mix_audio(voice_audio: Path, music_path: Path | None, out_path: Path):
    """Mix the voiceover over an optional background music bed."""
    if music_path is None:
        _run(["ffmpeg", "-y", "-i", str(voice_audio), "-c:a", "aac", "-b:a", "192k",
              str(out_path)])
        return out_path

    music_cfg = CONFIG.get("music", {})
    volume = float(music_cfg.get("volume", 0.15))
    fade_in = float(music_cfg.get("fade_in_seconds", 2.0))
    m_dur = probe_duration(music_path)
    fade_out = min(3.0, max(0.5, m_dur - 0.5))
    fc = (
        f"[1:a]volume={volume},afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={m_dur - fade_out:.3f}:d={fade_out:.3f}[m];"
        f"[0:a][m]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
    )
    _run([
        "ffmpeg", "-y", "-i", str(voice_audio), "-i", str(music_path),
        "-filter_complex", fc,
        "-map", "[aout]", "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ])
    return out_path


def build(
    scene_videos: list[Path],
    voice_audio: Path,
    captions_ass: Path,
    words: list[dict],
    scenes: list[dict],
    out_path: Path,
    work_dir: Path,
) -> Path:
    v = CONFIG["video"]
    w, h, fps = v["width"], v["height"], v["fps"]
    work_dir.mkdir(parents=True, exist_ok=True)

    durations = _scene_durations(words, scenes)
    voice_dur = probe_duration(voice_audio)
    total = sum(durations)
    if voice_dur - total > 0.5:
        # Never cut the narration short — extend the last scene to cover the
        # full voiceover (edge-tts trailing silence included).
        durations[-1] += voice_dur - total
    prepped = []
    for i, (src, dur) in enumerate(zip(scene_videos, durations)):
        out = work_dir / f"prep_{i:02d}.mp4"
        _prep_scene_clip(src, dur, out, w, h, fps)
        prepped.append(out)

    concat_list = work_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in prepped),
        encoding="utf-8",
    )

    silent = work_dir / "silent.mp4"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(silent),
    ])

    music_path = music.build(voice_dur, work_dir)
    mixed_audio = work_dir / "mixed.m4a"
    _mix_audio(voice_audio, music_path, mixed_audio)

    ass_arg = str(captions_ass).replace("\\", "/").replace(":", "\\:")
    fonts_arg = str(ROOT / "assets" / "fonts").replace("\\", "/").replace(":", "\\:")
    _run([
        "ffmpeg", "-y", "-i", str(silent), "-i", str(mixed_audio),
        "-vf", f"subtitles='{ass_arg}':fontsdir='{fonts_arg}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ])
    return out_path
