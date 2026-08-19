"""Faceless YouTube Automation Studio — tkinter GUI for both pipelines.

Design: consumer-style dark app with a sidebar, live % progress for each
pipeline (parsed from their stage output), and output cards with one-click
open. The Generator creates faceless videos from a topic; the Clipper chops a
long video into vertical shorts. Run:

    uv run gui.py
"""
import os
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yaml

ROOT = Path(__file__).resolve().parent
GEN_DIR = ROOT / "generator"
CLIP_DIR = ROOT / "clipper"
GEN_PY = GEN_DIR / ".venv" / "Scripts" / "python.exe"
CLIP_PY = CLIP_DIR / ".venv" / "Scripts" / "python.exe"
GEN_CONFIG = GEN_DIR / "config.yaml"

_FFMPEG_PKG = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
_FFMPEG_DIR = next(
    (_FFMPEG_PKG / p / "ffmpeg-9.0-full_build" / "bin"
     for p in os.listdir(_FFMPEG_PKG) if p.startswith("Gyan.FFmpeg"))
    if _FFMPEG_PKG.exists() else iter(()), None
)

VOICES = [
    "en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-EricNeural",
    "en-US-JennyNeural", "en-US-AriaNeural", "en-US-MichelleNeural",
    "en-GB-SoniaNeural", "en-GB-RyanNeural",
    "en-AU-WilliamNeural", "en-AU-NatashaNeural",
]
ASPECTS = ["9:16", "1:1", "16:9"]

# ---------------------------------------------------------------- palette ---
BG = "#0b0e15"
SURFACE = "#12161f"
SURFACE2 = "#1a2030"
SURFACE3 = "#232c41"
BORDER = "#2d3750"
FG = "#e9edf6"
MUTED = "#8d97ad"
ACCENT = "#6d7cff"
ACCENT2 = "#8f9bff"
ACCENT_DIM = "#1b2140"
GREEN = "#3ddc97"
PINK = "#f472b6"
RED = "#ff6b6b"
YELLOW = "#ffd166"
DANGER = "#8f2d3d"

# ------------------------------------------------------- generator stages ---
GEN_STAGES = [
    (re.compile(r"\[1/7\]"), ("Writing script", 8)),
    (re.compile(r"\[2/7\]"), ("Synthesizing voiceover", 10)),
    (re.compile(r"\[3/7\]"), ("Transcribing audio (Whisper)", 22)),
    (re.compile(r"\[4/7\]"), ("Fetching b-roll (Pexels)", 22)),
    (re.compile(r"\[5/7\]"), ("Writing captions", 5)),
    (re.compile(r"\[6/7\]"), ("Assembling video (ffmpeg)", 28)),
    (re.compile(r"\[7/7\]"), ("Uploading to YouTube", 5)),
]

CLIP_STAGES = [
    (re.compile(r"\[download/local\]"), ("Downloading source", 15)),
    (re.compile(r"\[transcribe/local\]"), ("Transcribing (Whisper)", 30)),
    (re.compile(r"\[highlights\]"), ("Ranking highlights (AI)", 25)),
]
CLIP_RENDER_BASE = 70
CLIP_RENDER_WEIGHT = 30


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _run_env() -> dict:
    env = dict(os.environ)
    if _FFMPEG_DIR and _FFMPEG_DIR.exists():
        env["PATH"] = str(_FFMPEG_DIR) + os.pathsep + env.get("PATH", "")
    return env


# ------------------------------------------------------- generator config ---
DEFAULT_GEN = {
    "niche": "Japanese culture (history, food, traditions, festivals, landmarks, daily life, anime history, etiquette)",
    "audience": "people fascinated by Japan who want to learn surprising cultural facts",
    "language": "en",
    "script": {"model": "meta/llama-3.3-70b-instruct", "target_seconds": 120, "words_per_second": 2.5},
    "voice": {"provider": "edge", "voice": "en-US-ChristopherNeural", "rate": "-12%", "pitch": "+0Hz"},
    "music": {"enabled": True, "volume": 0.15, "fade_in_seconds": 2, "tail_seconds": 4, "file": ""},
    "captions": {"whisper_model": "base", "font": "Anton", "font_size": 90,
                 "primary_color": "&H00FFFFFF", "outline_color": "&H00000000",
                 "outline": 6, "words_per_caption": 3, "position_y": 0.55},
    "video": {"width": 1080, "height": 1920, "fps": 30},
    "upload": {"privacy": "public", "category_id": "27", "made_for_kids": False,
               "default_tags": ["shorts", "japan", "japaneseculture", "didyouknow", "education", "travel"]},
    "comments": {"model": "meta/llama-3.1-8b-instruct", "poll_interval_minutes": 180,
                 "auto_reply": True, "delete_spam": True},
}


def _deep_merge(base: dict, extra: dict):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def load_gen_config() -> dict:
    import copy
    cfg = copy.deepcopy(DEFAULT_GEN)
    try:
        if GEN_CONFIG.exists():
            loaded = yaml.safe_load(GEN_CONFIG.read_text(encoding="utf-8")) or {}
            _deep_merge(cfg, loaded)
    except Exception:
        pass
    return cfg


def save_gen_config(cfg: dict):
    GEN_CONFIG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ------------------------------------------------------------- progress -----
class PipeProgress:
    def __init__(self):
        self.pct = 0.0
        self.target = 0.0
        self.stage = "Waiting"
        self.running = False

    def start(self, label="Starting"):
        self.running = True
        self.pct = 2.0
        self.target = 4.0
        self.stage = label

    def set_stage(self, base: float, weight: float, label: str):
        self.pct = max(self.pct, base + 1.0)
        self.target = base + weight
        self.stage = label

    def set_pct(self, pct: float, label: str):
        self.pct = max(self.pct, pct)
        self.target = max(self.target, pct + 1)
        self.stage = label

    def tick(self) -> int:
        if self.running and self.target > self.pct:
            self.pct += (self.target - self.pct) * 0.08
            if self.pct >= self.target:
                self.pct = self.target * 0.99
        return int(min(100.0, self.pct))

    def finish(self):
        self.running = False
        self.pct = 100.0
        self.stage = "Done"


# ------------------------------------------------------------- proc thread --
class ProcThread(threading.Thread):
    def __init__(self, q, tag: str, cmd, cwd: Path, env=None):
        super().__init__(daemon=True)
        self.q = q
        self.tag = tag
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.proc = None

    def run(self):
        try:
            self.proc = subprocess.Popen(
                self.cmd, cwd=str(self.cwd), env=self.env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            for line in self.proc.stdout:
                self.q.put((self.tag, line.rstrip()))
            self.proc.wait()
        except Exception as e:
            self.q.put((self.tag, f"launch error: {e}"))
        finally:
            self.q.put((self.tag, None))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


# ------------------------------------------------------------------- app ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Faceless Studio")
        self.geometry("1240x860")
        self.minsize(1020, 700)
        self.configure(bg=BG)
        self.q: "queue.Queue" = queue.Queue()
        self.procs: dict[str, ProcThread] = {}
        self.gen_prog = PipeProgress()
        self.clip_prog = PipeProgress()
        self._last_gen_pct = -1
        self._last_clip_pct = -1
        self._view = "create"
        self._build_styles()
        self._build_ui()
        self._poll_queue()
        self._tick_progress()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------- styles -----
    def _build_styles(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass

        st.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("Surface.TFrame", background=SURFACE)
        st.configure("Card.TFrame", background=SURFACE2)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Surface.TLabel", background=SURFACE, foreground=FG)
        st.configure("Card.TLabel", background=SURFACE2, foreground=FG)
        st.configure("Muted.TLabel", background=SURFACE2, foreground=MUTED)
        st.configure("H1.TLabel", background=BG, foreground=FG, font=("Segoe UI", 21, "bold"))
        st.configure("Tag.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Section.TLabel", background=SURFACE2, foreground=MUTED,
                     font=("Segoe UI", 10, "bold"))
        st.configure("CardTitle.TLabel", background=SURFACE2, foreground=FG,
                     font=("Segoe UI", 12, "bold"))
        st.configure("Stage.TLabel", background=SURFACE2, foreground=MUTED, font=("Segoe UI", 10))
        st.configure("Pct.TLabel", background=SURFACE2, foreground=ACCENT,
                     font=("Segoe UI", 14, "bold"))
        st.configure("Pill.TLabel", background=SURFACE, foreground=GREEN,
                     font=("Segoe UI", 10, "bold"))

        st.configure("TButton", background=SURFACE3, foreground=FG, borderwidth=1,
                     focusthickness=0, padding=(14, 8))
        st.map("TButton", background=[("active", "#2e3a55"), ("disabled", "#1b212f")],
               foreground=[("disabled", MUTED)])
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                     font=("Segoe UI", 12, "bold"), padding=(22, 12))
        st.map("Accent.TButton", background=[("active", ACCENT2), ("disabled", "#3a4166")],
               foreground=[("disabled", "#aab0d4")])
        st.configure("Danger.TButton", background=DANGER, foreground="#fff",
                     font=("Segoe UI", 11, "bold"), padding=(16, 10))
        st.map("Danger.TButton", background=[("active", "#a53a4d"), ("disabled", "#3c2a30")])
        st.configure("Ghost.TButton", background=SURFACE2, foreground=FG, borderwidth=1,
                     padding=(12, 7))
        st.map("Ghost.TButton", background=[("active", SURFACE3)])

        st.configure("Nav.TButton", background=SURFACE, foreground=MUTED,
                     font=("Segoe UI", 12), padding=(18, 13), borderwidth=0, anchor="w")
        st.map("Nav.TButton", background=[("active", SURFACE2)])
        st.configure("NavActive.TButton", background=SURFACE2, foreground=FG,
                     font=("Segoe UI", 12, "bold"), padding=(18, 13), borderwidth=0, anchor="w")
        st.map("NavActive.TButton", background=[("active", SURFACE2)])

        st.configure("TCheckbutton", background=SURFACE2, foreground=FG, focuscolor=SURFACE2)
        st.map("TCheckbutton", background=[("active", SURFACE2)])
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=SURFACE3,
                     borderwidth=0, thickness=8)

    def _entry(self, parent, value="", width=34, show=None):
        e = tk.Entry(parent, bg=SURFACE3, fg=FG, insertbackground=FG, relief="flat",
                     font=("Segoe UI", 10), width=width, show=show,
                     highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        e.insert(0, value)
        return e

    def _spin(self, parent, lo, hi, val, width=8):
        s = tk.Spinbox(parent, from_=lo, to=hi, width=width, bg=SURFACE3, fg=FG,
                       insertbackground=FG, buttonbackground=SURFACE2, relief="flat",
                       highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        s.delete(0, "end")
        s.insert(0, val)
        return s

    def _card(self, parent, title, section=None):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", padx=2, pady=(0, 14))
        head = ttk.Frame(card, style="Card.TFrame")
        head.pack(fill="x", padx=18, pady=(16, 4))
        if section:
            ttk.Label(head, text=section.upper(), style="Section.TLabel").pack(anchor="w")
        ttk.Label(head, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(2, 0))
        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill="x", padx=18, pady=(4, 16))
        return card, body

    # ------------------------------------------------------------ layout ----
    def _build_ui(self):
        self._header()
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self._nav(root)
        self.main = ttk.Frame(root, style="Surface.TFrame")
        self.main.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.views: dict[str, ttk.Frame] = {}
        self.views["create"] = self._build_create(self.main)
        self.views["clip"] = self._build_clip(self.main)
        self.views["guide"] = self._build_guide(self.main)
        self._set_view("create")
        self._build_console()

    def _header(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=20, pady=(16, 14))
        brand = ttk.Frame(head)
        brand.pack(side="left")
        dot = tk.Canvas(brand, width=26, height=26, bg=BG, highlightthickness=0)
        dot.create_rectangle(3, 3, 23, 23, fill=ACCENT, outline="")
        dot.create_text(13, 13, text="F", fill="#fff", font=("Segoe UI", 12, "bold"))
        dot.pack(side="left")
        ttk.Label(brand, text="Faceless Studio", style="H1.TLabel").pack(side="left", padx=(12, 0))
        ttk.Label(brand, text="AI video factory  ·  generator + clipper", style="Tag.TLabel").pack(anchor="w", padx=(38, 0))
        self.status_pill = ttk.Label(head, text="●  Ready", style="Pill.TLabel")
        self.status_pill.pack(side="right")

    def _nav(self, root):
        nav = ttk.Frame(root, style="Surface.TFrame", width=210)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        ttk.Label(nav, text="MENU", style="Tag.TLabel").pack(anchor="w", padx=20, pady=(18, 6))
        self.nav_btns: dict[str, ttk.Button] = {}
        for key, label in (("create", "Create Video"), ("clip", "Clip to Shorts"), ("guide", "Guide")):
            b = ttk.Button(nav, text=label, style="Nav.TButton",
                           command=lambda k=key: self._set_view(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_btns[key] = b
        ttk.Label(nav, text="LOCAL  ·  NVIDIA NIM  ·  FREE", style="Tag.TLabel").pack(
            side="bottom", anchor="w", padx=20, pady=16)

    def _set_view(self, key: str):
        self._view = key
        for k, f in self.views.items():
            f.pack_forget()
        self.views[key].pack(fill="both", expand=True, padx=18, pady=16)
        for k, b in self.nav_btns.items():
            b.configure(style="NavActive.TButton" if k == key else "Nav.TButton")

    # ------------------------------------------------------- CREATE view ----
    def _build_create(self, parent):
        v = ttk.Frame(parent, style="Surface.TFrame")
        cfg = load_gen_config()

        card, body = self._card(v, "Content", "1 · Niche")
        ttk.Label(body, text="Niche", style="Muted.TLabel").pack(anchor="w")
        self.niche_txt = tk.Text(body, height=3, bg=SURFACE3, fg=FG, insertbackground=FG,
                                 relief="flat", font=("Segoe UI", 10), highlightthickness=1,
                                 highlightbackground=BORDER, highlightcolor=ACCENT)
        self.niche_txt.insert("1.0", cfg["niche"])
        self.niche_txt.pack(fill="x", pady=(4, 10))
        ttk.Label(body, text="Audience", style="Muted.TLabel").pack(anchor="w")
        self.audience_e = self._entry(body, cfg["audience"])
        self.audience_e.pack(fill="x", pady=(4, 0))

        card, body = self._card(v, "Script, Voice & Music", "2 · Style")
        grid = ttk.Frame(body, style="Card.TFrame")
        grid.pack(fill="x")
        for c in range(4):
            grid.columnconfigure(c, weight=1)
        ttk.Label(grid, text="Length", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="Voice", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(grid, text="Music", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(14, 0))
        ttk.Label(grid, text="", style="Muted.TLabel").grid(row=0, column=3)
        self.seconds_sb = self._spin(grid, 30, 180, cfg["script"]["target_seconds"])
        self.seconds_sb.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.voice_cb = ttk.Combobox(grid, values=VOICES, width=26, state="readonly")
        self.voice_cb.set(cfg["voice"]["voice"])
        self.voice_cb.grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(4, 0))
        self.music_on = tk.BooleanVar(value=cfg["music"]["enabled"])
        ttk.Checkbutton(grid, text="Ambient music", variable=self.music_on,
                        style="TCheckbutton").grid(row=1, column=2, sticky="w", padx=(14, 0))
        vol = ttk.Frame(grid, style="Card.TFrame")
        vol.grid(row=2, column=2, sticky="w", padx=(14, 0), pady=(10, 0))
        ttk.Label(vol, text="vol", style="Muted.TLabel").pack(side="left")
        self.music_vol = ttk.Scale(vol, from_=0, to=50, orient="horizontal", length=120,
                                   command=lambda _v: self._sync_music_vol())
        self.music_vol.set(int(cfg["music"]["volume"] * 100))
        self.music_vol.pack(side="left", padx=(8, 6))
        self.music_vol_lbl = ttk.Label(vol, text=f"{int(cfg['music']['volume'] * 100)}%",
                                       style="Muted.TLabel")
        self.music_vol_lbl.pack(side="left")

        card, body = self._card(v, "Publishing", "3 · Deliver")
        self.upload_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Upload to YouTube after building (requires OAuth setup)",
                        variable=self.upload_on, style="TCheckbutton").pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Publish at  (ISO UTC, e.g. 2026-08-20T14:00:00Z)", style="Muted.TLabel").pack(side="left")
        self.publish_e = self._entry(row, "", width=34)
        self.publish_e.pack(side="left", padx=(12, 0))

        card, body = self._card(v, "Run", "4 · Generate")
        self.gen_bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.gen_bar.pack(fill="x")
        pr = ttk.Frame(body, style="Card.TFrame")
        pr.pack(fill="x", pady=(8, 0))
        self.gen_stage = ttk.Label(pr, text="Idle", style="Stage.TLabel")
        self.gen_stage.pack(side="left")
        self.gen_pct = ttk.Label(pr, text="0%", style="Pct.TLabel")
        self.gen_pct.pack(side="right")
        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        self.gen_run_btn = ttk.Button(btns, text="Generate Video", style="Accent.TButton",
                                      command=self.run_generator)
        self.gen_run_btn.pack(side="left")
        self.gen_stop_btn = ttk.Button(btns, text="Stop", style="Danger.TButton",
                                       state="disabled", command=lambda: self._stop("generator"))
        self.gen_stop_btn.pack(side="left", padx=(12, 0))

        card, body = self._card(v, "Latest Output", "5 · Result")
        self.gen_out = ttk.Label(body, text="No video generated yet", style="Muted.TLabel")
        self.gen_out.pack(anchor="w")
        out_row = ttk.Frame(body, style="Card.TFrame")
        out_row.pack(fill="x", pady=(10, 0))
        ttk.Button(out_row, text="Open File", style="Ghost.TButton",
                   command=lambda: self._open_gen_file()).pack(side="left")
        ttk.Button(out_row, text="Open Folder", style="Ghost.TButton",
                   command=lambda: self._open_output(GEN_DIR / "output")).pack(side="left", padx=(10, 0))
        self._gen_out_path: Path | None = None
        return v

    def _sync_music_vol(self):
        if getattr(self, "music_vol_lbl", None) is not None:
            self.music_vol_lbl.configure(text=f"{int(float(self.music_vol.get()))}%")

    # --------------------------------------------------------- CLIP view ----
    def _build_clip(self, parent):
        v = ttk.Frame(parent, style="Surface.TFrame")

        card, body = self._card(v, "Source Video", "1 · Input")
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        self.clip_src = self._entry(row, "", width=50)
        self.clip_src.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", style="Ghost.TButton",
                   command=self._browse_clip_src).pack(side="left", padx=(10, 0))

        card, body = self._card(v, "Shorts", "2 · Settings")
        grid = ttk.Frame(body, style="Card.TFrame")
        grid.pack(fill="x")
        for c in range(3):
            grid.columnconfigure(c, weight=1)
        ttk.Label(grid, text="Clips", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="Aspect ratio", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(grid, text="Min length (s)", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.clip_num = self._spin(grid, 1, 8, 3)
        self.clip_num.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.clip_ratio = ttk.Combobox(grid, values=ASPECTS, width=10, state="readonly")
        self.clip_ratio.set("9:16")
        self.clip_ratio.grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(4, 0))
        self.clip_min = self._spin(grid, 10, 120, 30)
        self.clip_min.grid(row=1, column=2, sticky="w", padx=(14, 0), pady=(4, 0))

        card, body = self._card(v, "Output Folder", "3 · Destination")
        orow = ttk.Frame(body, style="Card.TFrame")
        orow.pack(fill="x")
        self.clip_out = self._entry(orow, str(CLIP_DIR / "output"), width=50)
        self.clip_out.pack(side="left", fill="x", expand=True)
        ttk.Button(orow, text="Browse", style="Ghost.TButton",
                   command=self._browse_clip_out).pack(side="left", padx=(10, 0))

        card, body = self._card(v, "Run", "4 · Clip")
        self.clip_bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.clip_bar.pack(fill="x")
        pr = ttk.Frame(body, style="Card.TFrame")
        pr.pack(fill="x", pady=(8, 0))
        self.clip_stage = ttk.Label(pr, text="Idle", style="Stage.TLabel")
        self.clip_stage.pack(side="left")
        self.clip_pct = ttk.Label(pr, text="0%", style="Pct.TLabel")
        self.clip_pct.pack(side="right")
        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        self.clip_run_btn = ttk.Button(btns, text="Clip Video", style="Accent.TButton",
                                       command=self.run_clipper)
        self.clip_run_btn.pack(side="left")
        self.clip_stop_btn = ttk.Button(btns, text="Stop", style="Danger.TButton",
                                        state="disabled", command=lambda: self._stop("clipper"))
        self.clip_stop_btn.pack(side="left", padx=(12, 0))

        card, body = self._card(v, "Latest Shorts", "5 · Result")
        self.clip_out_lbl = ttk.Label(body, text="No shorts generated yet", style="Muted.TLabel")
        self.clip_out_lbl.pack(anchor="w")
        out_row = ttk.Frame(body, style="Card.TFrame")
        out_row.pack(fill="x", pady=(10, 0))
        ttk.Button(out_row, text="Open Folder", style="Ghost.TButton",
                   command=self._open_output).pack(side="left")
        return v

    def _browse_clip_src(self):
        p = filedialog.askopenfilename(title="Choose a video file",
                                       filetypes=[("Video", "*.mp4 *.mov *.mkv *.webm"), ("All files", "*.*")])
        if p:
            self.clip_src.delete(0, "end")
            self.clip_src.insert(0, p)

    def _browse_clip_out(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.clip_out.delete(0, "end")
            self.clip_out.insert(0, d)

    def _open_output(self, default=None):
        target = default if default is not None else Path(self.clip_out.get()).resolve()
        os.makedirs(target, exist_ok=True)
        os.startfile(str(target))  # noqa: S606

    def _open_gen_file(self):
        if self._gen_out_path and self._gen_out_path.exists():
            os.startfile(str(self._gen_out_path))  # noqa: S606

    # ------------------------------------------------------- GUIDE view ----
    def _build_guide(self, parent):
        v = ttk.Frame(parent, style="Surface.TFrame")
        txt = tk.Text(v, bg=SURFACE, fg=FG, wrap="word", relief="flat", font=("Consolas", 10),
                      padx=22, pady=18, insertbackground=FG)
        sb = ttk.Scrollbar(v, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.configure(state="disabled")
        guide = (
            "HOW TO USE\n"
            "==========\n"
            "\n"
            "1.  ONE-TIME SETUP\n"
            "    - ffmpeg:            winget install Gyan.FFmpeg\n"
            "    - NVIDIA NIM key:    https://build.nvidia.com   -> put in generator/.env\n"
            "                           and clipper/.env (NVIDIA_API_KEY, LLM_PROVIDER=nvidia)\n"
            "    - Pexels key:        https://www.pexels.com/api/ -> generator/.env\n"
            "\n"
            "2.  CREATE VIDEO  (faceless video from scratch)\n"
            "    a. Set Niche and Audience, e.g. Japanese culture / street food.\n"
            "    b. Choose length, voice, and music volume.\n"
            "    c. Press Generate Video. Stages run automatically:\n"
            "         script (AI) -> voiceover -> Whisper captions\n"
            "         -> b-roll (Pexels) -> ffmpeg assemble + music\n"
            "    d. Result: generator/output/<timestamp>_<topic>/final.mp4\n"
            "    e. To upload, run once:  generator\\.venv\\Scripts\\python.exe -m src.authorize\n"
            "       then tick 'Upload to YouTube'.\n"
            "\n"
            "3.  CLIP TO SHORTS  (chop a long video into vertical shorts)\n"
            "    a. Source: paste a YouTube URL or a local file path (or Browse).\n"
            "    b. Set clip count, aspect ratio (9:16 = Shorts/Reels), and min length.\n"
            "    c. Press Clip Video:\n"
            "         download -> Whisper transcript -> AI ranks highlights\n"
            "         -> face-tracked 9:16 crop -> captions\n"
            "    d. Result: clipper/output/short_01.mp4 ...\n"
            "\n"
            "4.  TWEAKS\n"
            "    - generator/config.yaml : niche, length, voice, music, captions.\n"
            "    - clipper/.env : LOCAL_MIN_CLIP_DURATION, LOCAL_WHISPER_MODEL.\n"
            "\n"
            "5.  COSTS  (all free tiers)\n"
            "    NVIDIA NIM free (rate-limited) | edge-tts free | Whisper local free\n"
            "    Pexels free | YouTube API free quota\n"
        )
        txt.configure(state="normal")
        txt.insert("1.0", guide)
        txt.configure(state="disabled")
        return v

    # ------------------------------------------------------------ console ---
    def _build_console(self):
        wrap = ttk.Frame(self, style="Surface.TFrame")
        wrap.pack(fill="x", padx=16, pady=(0, 10))
        head = ttk.Frame(wrap, style="Surface.TFrame")
        head.pack(fill="x", padx=4, pady=(4, 0))
        self.console_visible = tk.BooleanVar(value=True)
        ttk.Label(head, text="CONSOLE", style="Section.TLabel").pack(side="left")
        self.console_toggle = ttk.Button(head, text="Hide", style="Ghost.TButton",
                                         command=self._toggle_console)
        self.console_toggle.pack(side="right")
        ttk.Button(head, text="Clear", style="Ghost.TButton",
                   command=self._clear_console).pack(side="right", padx=(0, 8))
        self.console = tk.Text(wrap, bg="#080a10", fg=MUTED, wrap="word", relief="flat",
                               font=("Consolas", 9), height=11, state="disabled",
                               insertbackground=FG, padx=10, pady=6)
        sb = ttk.Scrollbar(wrap, command=self.console.yview)
        self.console.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)
        for tag, color in (("gen", GREEN), ("clip", PINK), ("sys", ACCENT2),
                           ("err", RED), ("warn", YELLOW), ("ok", GREEN)):
            self.console.tag_configure(tag, foreground=color)

    def _toggle_console(self):
        vis = not self.console_visible.get()
        self.console_visible.set(vis)
        if vis:
            self.console.pack(side="left", fill="both", expand=True)
            self.console_toggle.configure(text="Hide")
        else:
            self.console.pack_forget()
            self.console_toggle.configure(text="Show")

    def _log(self, tag, line, level="sys"):
        color = level if level in ("gen", "clip", "sys", "err", "warn", "ok") else "sys"
        self.console.configure(state="normal")
        self.console.insert("end", f"{_now()}  [{tag}] {line}\n", (color,))
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _detect_level(self, line: str) -> str:
        low = line.lower()
        if any(w in low for w in ("traceback", "error", "failed", "exception", "invalid")):
            return "err"
        if "warn" in low or "retrying" in low:
            return "warn"
        return "sys"

    # ----------------------------------------------------- progress tick ----
    def _tick_progress(self):
        g = self.gen_prog.tick()
        if g != self._last_gen_pct:
            self._last_gen_pct = g
            self.gen_bar.configure(value=g)
            self.gen_pct.configure(text=f"{g}%")
        self.gen_stage.configure(text=self.gen_prog.stage)
        c = self.clip_prog.tick()
        if c != self._last_clip_pct:
            self._last_clip_pct = c
            self.clip_bar.configure(value=c)
            self.clip_pct.configure(text=f"{c}%")
        self.clip_stage.configure(text=self.clip_prog.stage)
        self.after(200, self._tick_progress)

    def _poll_queue(self):
        try:
            while True:
                tag, line = self.q.get_nowait()
                if line is None:
                    self._proc_done(tag)
                    continue
                self._log(tag, line, self._detect_level(line))
                if tag == "generator":
                    self._parse_gen_progress(line)
                elif tag == "clipper":
                    self._parse_clip_progress(line)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _parse_gen_progress(self, line: str):
        for idx, (rx, (label, weight)) in enumerate(GEN_STAGES):
            if rx.search(line):
                base = sum(w for _, (_, w) in GEN_STAGES[:idx])
                self.gen_prog.set_stage(base, weight, label)
                return

    def _parse_clip_progress(self, line: str):
        m = re.search(r"\[clip/local\]\s+(\d+)/(\d+)", line)
        if m:
            i, total = int(m.group(1)), int(m.group(2))
            self.clip_prog.set_pct(CLIP_RENDER_BASE + (i - 1) / max(total, 1) * CLIP_RENDER_WEIGHT,
                                   f"Rendering clip {i}/{total}")
            return
        for idx, (rx, (label, weight)) in enumerate(CLIP_STAGES):
            if rx.search(line):
                base = sum(w for _, (_, w) in CLIP_STAGES[:idx])
                self.clip_prog.set_stage(base, weight, label)
                return

    # ----------------------------------------------------------- runners ----
    def _launch(self, tag, cmd, cwd, env=None):
        if tag in self.procs:
            messagebox.showwarning("Already running", f"The {tag} is already running.")
            return False
        self._log("system", f"launching {tag}: {' '.join(str(c) for c in cmd)}", "sys")
        if tag == "generator":
            self.gen_run_btn.configure(state="disabled")
            self.gen_stop_btn.configure(state="normal")
            self.gen_prog.start()
        else:
            self.clip_run_btn.configure(state="disabled")
            self.clip_stop_btn.configure(state="normal")
            self.clip_prog.start()
        self.status_pill.configure(text=f"●  {tag.title()} running", foreground=YELLOW)
        t = ProcThread(self.q, tag, cmd, cwd, env)
        self.procs[tag] = t
        t.start()
        return True

    def _stop(self, tag):
        t = self.procs.get(tag)
        if t:
            self._log("system", f"stopping {tag}...", "warn")
            t.stop()

    def _proc_done(self, tag):
        if tag not in self.procs:
            return
        self.procs.pop(tag)
        self._log("system", f"{tag} pipeline finished", "sys")
        if tag == "generator":
            self.gen_prog.finish()
            self.gen_run_btn.configure(state="normal")
            self.gen_stop_btn.configure(state="disabled")
            self._refresh_gen_output()
        elif tag == "clipper":
            self.clip_prog.finish()
            self.clip_run_btn.configure(state="normal")
            self.clip_stop_btn.configure(state="disabled")
            self._refresh_clip_output()
        self.status_pill.configure(text="●  Ready", foreground=GREEN)

    def run_generator(self):
        cfg = load_gen_config()
        cfg["niche"] = self.niche_txt.get("1.0", "end").strip()
        cfg["audience"] = self.audience_e.get().strip()
        cfg["script"]["target_seconds"] = int(float(self.seconds_sb.get() or 120))
        cfg["voice"]["voice"] = self.voice_cb.get()
        cfg["music"]["enabled"] = bool(self.music_on.get())
        cfg["music"]["volume"] = round(int(float(self.music_vol.get())) / 100.0, 2)
        save_gen_config(cfg)
        cmd = [str(GEN_PY), "-m", "src.pipeline"]
        if not self.upload_on.get():
            cmd.append("--no-upload")
        pub = self.publish_e.get().strip()
        if pub:
            cmd += ["--publish-at", pub]
        if self._launch("generator", cmd, GEN_DIR, _run_env()):
            self._log("ok", "Generator config saved. Building full video with music...")

    def run_clipper(self):
        src = self.clip_src.get().strip()
        if not src:
            messagebox.showerror("Missing source", "Enter a YouTube URL or choose a local video file.")
            return
        out = Path(self.clip_out.get().strip() or str(CLIP_DIR / "output"))
        cmd = [str(CLIP_PY), "main.py", src, "--mode", "local",
               "--num-clips", str(int(float(self.clip_num.get() or 3))),
               "--aspect-ratio", self.clip_ratio.get()]
        env = _run_env()
        env["LOCAL_MIN_CLIP_DURATION"] = str(int(float(self.clip_min.get() or 30)))
        env["LOCAL_OUTPUT_DIR"] = str(out)
        if self._launch("clipper", cmd, CLIP_DIR, env):
            self._log("ok", f"Clipper started. Output: {out}")

    # ------------------------------------------------------------ results ---
    def _refresh_gen_output(self):
        base = GEN_DIR / "output"
        if not base.exists():
            return
        dirs = [d for d in base.iterdir() if d.is_dir() and (d / "final.mp4").exists()]
        if not dirs:
            return
        latest = max(dirs, key=lambda d: d.stat().st_mtime)
        self._gen_out_path = latest / "final.mp4"
        self.gen_out.configure(text=f"final.mp4  ·  {_now()}", foreground=GREEN)

    def _refresh_clip_output(self):
        out = Path(self.clip_out.get().strip() or str(CLIP_DIR / "output"))
        if not out.exists():
            return
        shorts = sorted(out.glob("short_*.mp4"))
        if shorts:
            names = ", ".join(p.name for p in shorts)
            self.clip_out_lbl.configure(text=f"{len(shorts)} short(s): {names}",
                                        foreground=GREEN)

    def _on_close(self):
        for t in list(self.procs.values()):
            t.stop()
        self.destroy()


def main():
    app = App()
    if "--selftest" in sys.argv:
        app.after(1500, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()