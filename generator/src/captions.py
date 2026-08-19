from pathlib import Path
from faster_whisper import WhisperModel
from .config import CONFIG

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        size = CONFIG["captions"].get("whisper_model", "base")
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


def transcribe_words(audio_path: Path) -> list[dict]:
    model = _get_model()
    segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"word": w.word, "start": float(w.start), "end": float(w.end)})
    return words


def _fmt_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h:01d}:{m:02d}:{s:05.2f}"


def write_ass(words: list[dict], out_path: Path, video_w: int, video_h: int) -> Path:
    c = CONFIG["captions"]
    chunk_size = c["words_per_caption"]
    margin_v = int(video_h * (1 - c["position_y"]))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{c['font']},{c['font_size']},{c['primary_color']},&H00FFFFFF,{c['outline_color']},&H00000000,-1,0,0,0,100,100,0,0,1,{c['outline']},2,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        start = _fmt_ts(chunk[0]["start"])
        end = _fmt_ts(chunk[-1]["end"])
        text = " ".join(w["word"].strip() for w in chunk).upper()
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    out_path.write_text(header + "\n".join(lines), encoding="utf-8")
    return out_path
