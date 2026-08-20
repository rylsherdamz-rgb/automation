"""Faceless YouTube Automation Studio — tkinter GUI for both pipelines.

Design: consumer-style dark app with a sidebar, live % progress for each
pipeline (parsed from their stage output), environment health checks, and
clickable output history. The Generator creates faceless videos from a topic;
the Clipper chops a long video into vertical shorts. Run:

    uv run gui.py
"""
import copy
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yaml

if getattr(sys, "frozen", False):
    # Packaged app: the exe lives at dist/FacelessStudio/FacelessStudio.exe with
    # generator/ and clipper/ (incl. their venvs) copied next to it.
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
GEN_DIR = ROOT / "generator"
CLIP_DIR = ROOT / "clipper"
GEN_PY = GEN_DIR / ".venv" / "Scripts" / "python.exe"
CLIP_PY = CLIP_DIR / ".venv" / "Scripts" / "python.exe"
GEN_CONFIG = GEN_DIR / "config.yaml"
GEN_OUT_DIR = GEN_DIR / "output"
CLIP_OUT_DIR = CLIP_DIR / "output"
STATE_FILE = ROOT / "gui_state.json"
LOG_DIR = ROOT / "logs"
HISTORY_LIMIT = 12
VERSION = "2.0.0"

_FFMPEG_PKG = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"

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
SHIMMER = "#a8b4ff"
GREEN = "#3ddc97"
PINK = "#f472b6"
RED = "#ff6b6b"
YELLOW = "#ffd166"
ORANGE = "#ffb454"
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


def _fmt_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _find_ffmpeg_dir() -> Path | None:
    """Locate the WinGet-installed ffmpeg bin dir (any version)."""
    if not _FFMPEG_PKG.exists():
        return None
    try:
        for p in _FFMPEG_PKG.iterdir():
            if not p.name.startswith("Gyan.FFmpeg") or not p.is_dir():
                continue
            for d in p.iterdir():
                if (d / "bin" / "ffmpeg.exe").exists():
                    return d / "bin"
    except OSError:
        pass
    return None


def _run_env() -> dict:
    env = dict(os.environ)
    d = _find_ffmpeg_dir()
    if d:
        env["PATH"] = str(d) + os.pathsep + env.get("PATH", "")
    # Force child Python processes to flush stdout/stderr line-by-line so the
    # GUI receives stage markers live instead of in one big chunk at the end.
    env["PYTHONUNBUFFERED"] = "1"
    return env


def find_ffmpeg() -> str | None:
    """Resolve the ffmpeg executable that child pipelines will actually use."""
    env = _run_env()
    return shutil.which("ffmpeg", path=env.get("PATH", ""))


def _read_env(path: Path) -> dict:
    data = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict):
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


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
    IDLE, RUNNING, STOPPED, FAILED, DONE = range(5)

    def __init__(self):
        self.state = self.IDLE
        self.pct = 0.0
        self.target = 0.0
        self.stage = "Idle"
        self.started = 0.0
        self.stage_i = 0
        self.stage_n = 0
        self._breathe = 0

    def start(self, label="Starting"):
        self.state = self.RUNNING
        self.started = time.time()
        self.pct = 3.0
        self.target = 6.0
        self.stage = label
        self.stage_i = 0
        self.stage_n = 0
        self._breathe = 0

    def set_stage(self, base: float, weight: float, label: str, idx: int = 0, total: int = 0):
        if self.state != self.RUNNING:
            return
        self.pct = max(self.pct, base + 1.0)
        self.target = base + weight
        self.stage = label
        self.stage_i = idx
        self.stage_n = total
        self._breathe = 0

    def set_pct(self, pct: float, label: str):
        if self.state != self.RUNNING:
            return
        self.pct = max(self.pct, pct)
        self.target = max(self.target, pct + 1)
        self.stage = label
        self._breathe = 0

    def tick(self) -> int:
        if self.state != self.RUNNING:
            return int(min(100.0, self.pct))
        if self.pct < self.target:
            self.pct += (self.target - self.pct) * 0.10
            if self.pct >= self.target:
                self.pct = self.target
        else:
            # Breathing: while a stage is still working, slowly pulse near the
            # stage ceiling so the bar never looks frozen.
            self._breathe += 1
            phase = (self._breathe % 24) / 12
            self.pct = self.target - 0.6 + 0.6 * abs(phase - 1)
        return int(min(100.0, self.pct))

    def finish(self):
        self.state = self.DONE
        self.pct = 100.0
        self.stage = "Done"

    def fail(self, msg="Failed"):
        self.state = self.FAILED
        self.stage = msg

    def stop(self):
        self.state = self.STOPPED
        self.stage = "Stopped"

    def elapsed(self) -> float:
        return time.time() - self.started if self.started else 0.0


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
        self.stopped = False

    def run(self):
        code = -1
        try:
            self.proc = subprocess.Popen(
                self.cmd, cwd=str(self.cwd), env=self.env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            for line in self.proc.stdout:
                self.q.put((self.tag, line.rstrip()))
            self.proc.wait()
            code = self.proc.returncode
        except Exception as e:
            self.q.put((self.tag, f"launch error: {e}"))
            code = 1
        finally:
            self.q.put((self.tag, None, code))

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


# ------------------------------------------------------------------ widget ---
class RoundedProgress(tk.Canvas):
    """Smooth rounded progress bar with a sweeping shimmer while active."""

    def __init__(self, master, height=12, **kw):
        super().__init__(master, height=height, bg=SURFACE, highlightthickness=0,
                         bd=0, **kw)
        self._value = 0.0
        self._active = False
        self._phase = 0
        self.bind("<Configure>", lambda _e: self._redraw())

    def set(self, value: float, active: bool, phase: int = 0):
        self._value = max(0.0, min(100.0, value))
        self._active = active
        self._phase = phase
        self._redraw()

    def _rr(self, x0, y0, x1, y1, r, **kw):
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        r = max(0, min(r, (y1 - y0) / 2, (x1 - x0) / 2))
        self.create_arc(x0, y0, x0 + 2 * r, y0 + 2 * r, start=90, extent=90,
                        style="pieslice", **kw)
        self.create_arc(x1 - 2 * r, y0, x1, y0 + 2 * r, start=0, extent=90,
                        style="pieslice", **kw)
        self.create_arc(x0, y1 - 2 * r, x0 + 2 * r, y1, start=180, extent=90,
                        style="pieslice", **kw)
        self.create_arc(x1 - 2 * r, y1 - 2 * r, x1, y1, start=270, extent=90,
                        style="pieslice", **kw)
        self.create_rectangle(x0 + r, y0, x1 - r, y1, **kw)
        self.create_rectangle(x0, y0 + r, x1, y1 - r, **kw)

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height() or 12
        if w < 10:
            return
        r = h / 2
        self._rr(0, 0, w, h, r, fill=SURFACE3, outline="")
        fw = w * self._value / 100.0
        if fw >= 1.0:
            self._rr(0, 0, max(fw, h), h, r, fill=ACCENT, outline="")
        if self._active:
            band_w = w * 0.16
            cx = (self._phase % 40) / 40.0 * (w + band_w) - band_w / 2
            x0 = max(0.0, cx - band_w / 2)
            x1 = min(fw if fw > 0 else w, cx + band_w / 2)
            if x1 > x0:
                self._rr(x0, 1, x1, h - 1, r - 1, fill=SHIMMER, outline="")


# ------------------------------------------------------------------- app ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Faceless Studio")
        self.geometry("1280x880")
        self.minsize(1040, 720)
        self.configure(bg=BG)
        self.q: "queue.Queue" = queue.Queue()
        self.procs: dict[str, ProcThread] = {}
        self.gen_prog = PipeProgress()
        self.clip_prog = PipeProgress()
        self._last_gen_pct = -1
        self._last_clip_pct = -1
        self._last_error: dict[str, str] = {}
        self._run_log: dict[str, object] = {}          # tag -> (Path, file handle)
        self._last_log_path: dict[str, Path] = {}
        self._spinner = 0
        self._view = "create"
        self.state = _read_json(STATE_FILE)
        self._gen_out_path: Path | None = None
        self._gen_hist: list[tuple[str, Path]] = []
        self._clip_hist: list[tuple[str, Path]] = []
        self._build_styles()
        self._build_ui()
        self._jobs: list[str] = []
        self._poll_queue()
        self._tick_progress()
        self._jobs.append(self.after(400, self._doctor))
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
        st.configure("Foot.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("FootOk.TLabel", background=SURFACE, foreground=GREEN, font=("Segoe UI", 9, "bold"))
        st.configure("FootErr.TLabel", background=SURFACE, foreground=RED, font=("Segoe UI", 9, "bold"))
        st.configure("Section.TLabel", background=SURFACE2, foreground=MUTED,
                     font=("Segoe UI", 10, "bold"))
        st.configure("CardTitle.TLabel", background=SURFACE2, foreground=FG,
                     font=("Segoe UI", 12, "bold"))
        st.configure("Stage.TLabel", background=SURFACE2, foreground=MUTED, font=("Segoe UI", 10))
        st.configure("StageRunning.TLabel", background=SURFACE2, foreground=ACCENT2,
                     font=("Segoe UI", 10))
        st.configure("StageErr.TLabel", background=SURFACE2, foreground=RED, font=("Segoe UI", 10))
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
        st.map("Ghost.TButton", background=[("active", SURFACE3), ("disabled", SURFACE2)],
               foreground=[("disabled", MUTED)])

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
        st.configure("Sep.TSeparator", background=BORDER)
        st.configure("Chip.TLabel", background=ACCENT_DIM, foreground=ACCENT2,
                     font=("Segoe UI", 8, "bold"), padding=(8, 3))
        st.configure("ChipOk.TLabel", background="#143528", foreground=GREEN,
                     font=("Segoe UI", 8, "bold"), padding=(8, 3))

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

    def _listbox(self, parent, height=5):
        lb = tk.Listbox(parent, bg="#0e1220", fg=FG, relief="flat",
                        font=("Consolas", 9), height=height,
                        selectbackground=ACCENT_DIM, selectforeground=FG,
                        activestyle="none", exportselection=False,
                        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        return lb

    def _card(self, parent, title, section=None):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", padx=2, pady=(0, 14))
        head = ttk.Frame(card, style="Card.TFrame")
        head.pack(fill="x", padx=18, pady=(16, 2))
        if section:
            ttk.Label(head, text=section.upper(), style="Chip.TLabel").pack(anchor="w")
        ttk.Label(head, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(6, 0))
        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill="x", padx=18, pady=(6, 16))
        return card, body

    def _scroll_view(self, parent):
        """Create a scrollable canvas; the inner frame is a child of the canvas.

        Returns (canvas, inner) — pack cards into `inner`. The inner frame is a
        plain tk.Frame (the canonical canvas-window pattern) so it always draws.
        """
        canvas = tk.Canvas(parent, bg=SURFACE, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(parent, command=canvas.yview)
        inner = tk.Frame(canvas, bg=SURFACE)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)

        def _on_inner_cfg(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_cfg(e):
            canvas.itemconfigure(win_id, width=e.width)

        def _on_wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")

        inner.bind("<Configure>", _on_inner_cfg)
        canvas.bind("<Configure>", _on_canvas_cfg)
        for w in (canvas, inner):
            w.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
            w.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        return canvas, inner

    # ------------------------------------------------------------ layout ----
    def _build_ui(self):
        self._header()
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self._nav(root)
        self.main = ttk.Frame(root, style="Surface.TFrame")
        self.main.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.views: dict[str, tk.Widget] = {}
        self.views["create"] = self._build_create(self.main)
        self.views["clip"] = self._build_clip(self.main)
        self.views["guide"] = self._build_guide(self.main)
        self._set_view(self.state.get("view", "create"))
        self._build_console()
        self._build_statusbar()
        self._restore_state()

    def _header(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=20, pady=(14, 4))
        brand = ttk.Frame(head)
        brand.pack(side="left")
        logo = tk.Canvas(brand, width=30, height=30, bg=BG, highlightthickness=0)
        logo.create_rectangle(1, 1, 29, 29, fill=ACCENT, outline="")
        logo.create_rectangle(1, 15, 29, 29, fill=ACCENT2, outline="")
        logo.create_text(15, 16, text="F", fill="#0b0e15", font=("Segoe UI", 13, "bold"))
        logo.pack(side="left")
        brand2 = ttk.Frame(brand, style="TFrame")
        brand2.pack(side="left", padx=(12, 0))
        ttk.Label(brand2, text="Faceless Studio", style="H1.TLabel").pack(anchor="w")
        ttk.Label(brand2, text=f"AI video factory  ·  v{VERSION}", style="Tag.TLabel").pack(anchor="w")
        self.status_pill = ttk.Label(head, text="●  Ready", style="Pill.TLabel")
        self.status_pill.pack(side="right")
        ttk.Separator(self, style="Sep.TSeparator").pack(fill="x", padx=20, pady=(10, 6))

    def _nav(self, root):
        nav = ttk.Frame(root, style="Surface.TFrame", width=220)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        ttk.Label(nav, text="MENU", style="Tag.TLabel").pack(anchor="w", padx=22, pady=(18, 6))
        self.nav_btns: dict[str, ttk.Button] = {}
        for key, icon, label in (("create", "▶", "Create Video"),
                                 ("clip", "✂", "Clip to Shorts"),
                                 ("guide", "ℹ", "Guide")):
            b = ttk.Button(nav, text=f"{icon}   {label}", style="Nav.TButton",
                           command=lambda k=key: self._set_view(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_btns[key] = b
        ttk.Label(nav, text="LOCAL  ·  NVIDIA NIM  ·  FREE", style="Tag.TLabel").pack(
            side="bottom", anchor="w", padx=22, pady=16)

    def _set_view(self, key: str):
        self._view = key
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        for k, f in self.views.items():
            f.pack_forget()
        self.views[key].pack(fill="both", expand=True, padx=18, pady=16)
        for k, b in self.nav_btns.items():
            b.configure(style="NavActive.TButton" if k == key else "Nav.TButton")
        if key == "create":
            self._refresh_gen_history()
        elif key == "clip":
            self._refresh_clip_history()

    # ------------------------------------------------------- CREATE view ----
    def _build_create(self, parent):
        v = ttk.Frame(parent, style="Surface.TFrame")
        _, content = self._scroll_view(v)
        cfg = load_gen_config()

        card, body = self._card(content, "Content", "1 · Niche")
        ttk.Label(body, text="Niche", style="Muted.TLabel").pack(anchor="w")
        self.niche_txt = tk.Text(body, height=3, bg=SURFACE3, fg=FG, insertbackground=FG,
                                 relief="flat", font=("Segoe UI", 10), highlightthickness=1,
                                 highlightbackground=BORDER, highlightcolor=ACCENT)
        self.niche_txt.insert("1.0", cfg["niche"])
        self.niche_txt.pack(fill="x", pady=(4, 10))
        ttk.Label(body, text="Audience", style="Muted.TLabel").pack(anchor="w")
        self.audience_e = self._entry(body, cfg["audience"])
        self.audience_e.pack(fill="x", pady=(4, 0))

        card, body = self._card(content, "Script, Voice & Music", "2 · Style")
        grid = ttk.Frame(body, style="Card.TFrame")
        grid.pack(fill="x")
        for c in range(4):
            grid.columnconfigure(c, weight=1)
        ttk.Label(grid, text="Length (s)", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
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

        card, body = self._card(content, "Publishing", "3 · Deliver")
        self.upload_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Upload to YouTube after building (requires OAuth setup)",
                        variable=self.upload_on, style="TCheckbutton").pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Publish at  (ISO UTC, e.g. 2026-08-20T14:00:00Z)", style="Muted.TLabel").pack(side="left")
        self.publish_e = self._entry(row, "", width=34)
        self.publish_e.pack(side="left", padx=(12, 0))

        card, body = self._card(content, "Run", "4 · Generate")
        self.gen_bar = RoundedProgress(body, height=12)
        self.gen_bar.pack(fill="x")
        pr = ttk.Frame(body, style="Card.TFrame")
        pr.pack(fill="x", pady=(8, 0))
        self.gen_anim = ttk.Label(pr, text=" ", style="Card.TLabel",
                                  foreground=ACCENT, font=("Consolas", 11))
        self.gen_anim.pack(side="left")
        self.gen_stage = ttk.Label(pr, text="Idle", style="Stage.TLabel")
        self.gen_stage.pack(side="left", padx=(6, 0))
        self.gen_counter = ttk.Label(pr, text="", style="Stage.TLabel")
        self.gen_counter.pack(side="left", padx=(6, 0))
        self.gen_elapsed = ttk.Label(pr, text="", style="Stage.TLabel")
        self.gen_elapsed.pack(side="right", padx=(0, 10))
        self.gen_pct = ttk.Label(pr, text="0%", style="Pct.TLabel")
        self.gen_pct.pack(side="right")
        self.gen_log_btn = ttk.Button(body, text="View Run Log", style="Ghost.TButton",
                                      state="disabled", command=lambda: self._open_log("generator"))
        self.gen_log_btn.pack(anchor="e", pady=(10, 0))
        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        self.gen_run_btn = ttk.Button(btns, text="Generate Video", style="Accent.TButton",
                                      command=self.run_generator)
        self.gen_run_btn.pack(side="left")
        self.gen_stop_btn = ttk.Button(btns, text="Stop", style="Danger.TButton",
                                       state="disabled", command=lambda: self._stop("generator"))
        self.gen_stop_btn.pack(side="left", padx=(12, 0))

        card, body = self._card(content, "Output History", "5 · Results")
        self.gen_out = ttk.Label(body, text="No videos generated yet", style="Muted.TLabel")
        self.gen_out.pack(anchor="w")
        hist_frame = ttk.Frame(body, style="Card.TFrame")
        hist_frame.pack(fill="x", pady=(8, 0))
        self.gen_list = self._listbox(hist_frame, height=6)
        self.gen_list.pack(side="left", fill="both", expand=True)
        gsb = ttk.Scrollbar(hist_frame, command=self.gen_list.yview)
        self.gen_list.configure(yscrollcommand=gsb.set)
        gsb.pack(side="left", fill="y")
        self.gen_list.bind("<<ListboxSelect>>", self._on_gen_select)
        self.gen_list.bind("<Double-Button-1>", lambda _e: self._open_gen_file())
        out_row = ttk.Frame(body, style="Card.TFrame")
        out_row.pack(fill="x", pady=(10, 0))
        self.gen_open_btn = ttk.Button(out_row, text="Open File", style="Ghost.TButton",
                                       state="disabled", command=self._open_gen_file)
        self.gen_open_btn.pack(side="left")
        ttk.Button(out_row, text="Open Folder", style="Ghost.TButton",
                   command=lambda: self._open_output(GEN_OUT_DIR)).pack(side="left", padx=(10, 0))
        self.gen_copy_btn = ttk.Button(out_row, text="Copy Path", style="Ghost.TButton",
                                       state="disabled", command=self._copy_gen_path)
        self.gen_copy_btn.pack(side="left", padx=(10, 0))
        ttk.Button(out_row, text="Refresh", style="Ghost.TButton",
                   command=self._refresh_gen_history).pack(side="right")
        return v

    def _sync_music_vol(self):
        if getattr(self, "music_vol_lbl", None) is not None:
            self.music_vol_lbl.configure(text=f"{int(float(self.music_vol.get()))}%")

    # --------------------------------------------------------- CLIP view ----
    def _build_clip(self, parent):
        v = ttk.Frame(parent, style="Surface.TFrame")
        _, content = self._scroll_view(v)

        card, body = self._card(content, "Source Video", "1 · Input")
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        self.clip_src = self._entry(row, "", width=50)
        self.clip_src.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", style="Ghost.TButton",
                   command=self._browse_clip_src).pack(side="left", padx=(10, 0))

        card, body = self._card(content, "Shorts", "2 · Settings")
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

        card, body = self._card(content, "Output Folder", "3 · Destination")
        orow = ttk.Frame(body, style="Card.TFrame")
        orow.pack(fill="x")
        self.clip_out = self._entry(orow, str(CLIP_OUT_DIR), width=50)
        self.clip_out.pack(side="left", fill="x", expand=True)
        ttk.Button(orow, text="Browse", style="Ghost.TButton",
                   command=self._browse_clip_out).pack(side="left", padx=(10, 0))

        card, body = self._card(content, "Run", "4 · Clip")
        self.clip_bar = RoundedProgress(body, height=12)
        self.clip_bar.pack(fill="x")
        pr = ttk.Frame(body, style="Card.TFrame")
        pr.pack(fill="x", pady=(8, 0))
        self.clip_anim = ttk.Label(pr, text=" ", style="Card.TLabel",
                                   foreground=ACCENT, font=("Consolas", 11))
        self.clip_anim.pack(side="left")
        self.clip_stage = ttk.Label(pr, text="Idle", style="Stage.TLabel")
        self.clip_stage.pack(side="left", padx=(6, 0))
        self.clip_counter = ttk.Label(pr, text="", style="Stage.TLabel")
        self.clip_counter.pack(side="left", padx=(6, 0))
        self.clip_elapsed = ttk.Label(pr, text="", style="Stage.TLabel")
        self.clip_elapsed.pack(side="right", padx=(0, 10))
        self.clip_pct = ttk.Label(pr, text="0%", style="Pct.TLabel")
        self.clip_pct.pack(side="right")
        self.clip_log_btn = ttk.Button(body, text="View Run Log", style="Ghost.TButton",
                                       state="disabled", command=lambda: self._open_log("clipper"))
        self.clip_log_btn.pack(anchor="e", pady=(10, 0))
        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        self.clip_run_btn = ttk.Button(btns, text="Clip Video", style="Accent.TButton",
                                       command=self.run_clipper)
        self.clip_run_btn.pack(side="left")
        self.clip_stop_btn = ttk.Button(btns, text="Stop", style="Danger.TButton",
                                        state="disabled", command=lambda: self._stop("clipper"))
        self.clip_stop_btn.pack(side="left", padx=(12, 0))

        card, body = self._card(content, "Shorts History", "5 · Results")
        self.clip_out_lbl = ttk.Label(body, text="No shorts generated yet", style="Muted.TLabel")
        self.clip_out_lbl.pack(anchor="w")
        hist_frame = ttk.Frame(body, style="Card.TFrame")
        hist_frame.pack(fill="x", pady=(8, 0))
        self.clip_list = self._listbox(hist_frame, height=6)
        self.clip_list.pack(side="left", fill="both", expand=True)
        csb = ttk.Scrollbar(hist_frame, command=self.clip_list.yview)
        self.clip_list.configure(yscrollcommand=csb.set)
        csb.pack(side="left", fill="y")
        self.clip_list.bind("<<ListboxSelect>>", self._on_clip_select)
        self.clip_list.bind("<Double-Button-1>", lambda _e: self._open_clip_folder())
        out_row = ttk.Frame(body, style="Card.TFrame")
        out_row.pack(fill="x", pady=(10, 0))
        self.clip_open_btn = ttk.Button(out_row, text="Open Folder", style="Ghost.TButton",
                                        state="disabled", command=self._open_clip_folder)
        self.clip_open_btn.pack(side="left")
        self.clip_copy_btn = ttk.Button(out_row, text="Copy Path", style="Ghost.TButton",
                                        state="disabled", command=self._copy_clip_path)
        self.clip_copy_btn.pack(side="left", padx=(10, 0))
        ttk.Button(out_row, text="Refresh", style="Ghost.TButton",
                   command=self._refresh_clip_history).pack(side="right")
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

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log("system", f"copied to clipboard: {text}", "ok")

    def _copy_gen_path(self):
        if self._gen_out_path:
            self._copy(str(self._gen_out_path))

    def _copy_clip_path(self):
        if self._clip_selected:
            self._copy(str(self._clip_selected))

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
            "    Run the app and watch the status bar / console: it checks ffmpeg, keys,\n"
            "    and venvs for you at startup.\n"
            "\n"
            "2.  CREATE VIDEO  (faceless video from scratch)\n"
            "    a. Set Niche and Audience, e.g. Japanese culture / street food.\n"
            "    b. Choose length, voice, and music volume.\n"
            "    c. Press Generate Video. Stages run automatically:\n"
            "         script (AI) -> voiceover -> Whisper captions\n"
            "         -> b-roll (Pexels) -> ffmpeg assemble + music\n"
            "    d. Result: generator/output/<timestamp>_<topic>/final.mp4\n"
            "       Find it in the Output History list (open / copy path / open folder).\n"
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
            "    - All GUI settings are remembered between sessions.\n"
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
        wrap.pack(fill="x", padx=16, pady=(0, 8))
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
                               font=("Consolas", 9), height=9, state="disabled",
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

    # ------------------------------------------------------- status bar -----
    def _build_statusbar(self):
        bar = ttk.Frame(self, style="Surface.TFrame")
        bar.pack(fill="x", padx=16, pady=(0, 6))
        sep = tk.Frame(bar, bg=BORDER, height=1)
        sep.pack(fill="x")
        row = ttk.Frame(bar, style="Surface.TFrame")
        row.pack(fill="x", pady=(6, 2))
        self.env_lbl = ttk.Label(row, text="", style="Foot.TLabel")
        self.env_lbl.pack(side="left")
        self.out_lbl = ttk.Label(row, text="", style="Foot.TLabel")
        self.out_lbl.pack(side="right")

    def _refresh_statusbar(self, checks):
        parts = []
        for ok, text in checks:
            mark = "ok" if ok else "warn"
            style = "FootOk.TLabel" if ok else "FootErr.TLabel"
            parts.append((style, f"{'✓' if ok else '✗'} {text}"))
        self.env_lbl.configure(text="   ".join(t for _, t in parts))
        self.out_lbl.configure(text=f"outputs: {GEN_OUT_DIR}  ·  {CLIP_OUT_DIR}")

    def _doctor(self):
        """Environment health check, logged to the console and status bar."""
        checks = []
        if find_ffmpeg():
            checks.append((True, "ffmpeg: found"))
        else:
            checks.append((False, "ffmpeg: MISSING — winget install Gyan.FFmpeg"))
        checks.append((GEN_PY.exists(), "generator venv: present"))
        checks.append((CLIP_PY.exists(), "clipper venv: present"))
        gen_env = _read_env(GEN_DIR / ".env")
        checks.append((bool(gen_env.get("LLM_API_KEY")), "generator LLM key: set"))
        checks.append((bool(gen_env.get("PEXELS_API_KEY")), "Pexels key: set"))
        clip_env = _read_env(CLIP_DIR / ".env")
        clip_llm = any(clip_env.get(k) for k in ("NVIDIA_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"))
        checks.append((clip_llm, "clipper LLM key: set"))
        self._refresh_statusbar(checks)
        for ok, text in checks:
            self._log("doctor", text, "ok" if ok else "err")

    # ----------------------------------------------------- progress tick ----
    SPINNER = (" ", "●", "●○", "●○●", "●○", "●")

    def _tick_progress(self):
        try:
            self._spinner += 1
            spin = self.SPINNER[self._spinner % len(self.SPINNER)]

            g = self.gen_prog.tick()
            self.gen_bar.set(g, self.gen_prog.state == PipeProgress.RUNNING, self._spinner)
            self.gen_pct.configure(text=f"{g}%")
            self.gen_elapsed.configure(text=f"⏱ {_fmt_elapsed(self.gen_prog.elapsed())}")
            self.gen_stage.configure(text=self.gen_prog.stage)
            self._style_stage(self.gen_stage, self.gen_prog.state)
            self.gen_counter.configure(text=self._counter_text(self.gen_prog))
            self.gen_anim.configure(
                text=spin if self.gen_prog.state == PipeProgress.RUNNING else " ")

            c = self.clip_prog.tick()
            self.clip_bar.set(c, self.clip_prog.state == PipeProgress.RUNNING, self._spinner)
            self.clip_pct.configure(text=f"{c}%")
            self.clip_elapsed.configure(text=f"⏱ {_fmt_elapsed(self.clip_prog.elapsed())}")
            self.clip_stage.configure(text=self.clip_prog.stage)
            self._style_stage(self.clip_stage, self.clip_prog.state)
            self.clip_counter.configure(text=self._counter_text(self.clip_prog))
            self.clip_anim.configure(
                text=spin if self.clip_prog.state == PipeProgress.RUNNING else " ")
        except tk.TclError:
            return  # window destroyed; stop animating

        self._jobs.append(self.after(200, self._tick_progress))

    @staticmethod
    def _counter_text(prog) -> str:
        if prog.state == PipeProgress.RUNNING and prog.stage_i > 0:
            return f"stage {prog.stage_i}/{prog.stage_n}"
        return ""

    def _style_stage(self, lbl, state):
        style = "Stage.TLabel"
        if state == PipeProgress.RUNNING:
            style = "StageRunning.TLabel"
        elif state in (PipeProgress.FAILED,):
            style = "StageErr.TLabel"
        lbl.configure(style=style)

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                tag = item[0]
                if len(item) > 2 and item[1] is None:
                    self._proc_done(tag, item[2])
                    continue
                line = item[1]
                level = self._detect_level(line)
                self._log(tag, line, level)
                self._write_run_log(tag, line)
                if level == "err":
                    self._last_error[tag] = line
                if tag == "generator":
                    self._parse_gen_progress(line)
                elif tag == "clipper":
                    self._parse_clip_progress(line)
        except queue.Empty:
            pass
        self._jobs.append(self.after(80, self._poll_queue))

    def _write_run_log(self, tag: str, line: str):
        entry = self._run_log.get(tag)
        if not entry:
            return
        fh = entry[1]
        try:
            fh.write(f"{_now()}  {line}\n")
            fh.flush()
        except OSError:
            pass

    def _parse_gen_progress(self, line: str):
        for idx, (rx, (label, weight)) in enumerate(GEN_STAGES):
            if rx.search(line):
                base = sum(w for _, (_, w) in GEN_STAGES[:idx])
                self.gen_prog.set_stage(base, weight, label, idx + 1, len(GEN_STAGES))
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
                self.clip_prog.set_stage(base, weight, label, idx + 1, len(CLIP_STAGES))
                return

    # ----------------------------------------------------------- runners ----
    def _launch(self, tag, cmd, cwd, env=None):
        if tag in self.procs:
            messagebox.showwarning("Already running", f"The {tag} is already running.")
            return False
        self._save_state()
        self._last_error.pop(tag, None)
        self._open_run_log(tag, cmd)
        self._log("system", f"launching {tag}: {' '.join(str(c) for c in cmd)}", "sys")
        if tag == "generator":
            self.gen_run_btn.configure(state="disabled")
            self.gen_stop_btn.configure(state="normal")
            self.gen_log_btn.configure(state="disabled")
            self.gen_out.configure(text="Starting…", foreground=ACCENT2)
            self.gen_prog.start("Preparing…")
        else:
            self.clip_run_btn.configure(state="disabled")
            self.clip_stop_btn.configure(state="normal")
            self.clip_log_btn.configure(state="disabled")
            self.clip_out_lbl.configure(text="Starting…", foreground=ACCENT2)
            self.clip_prog.start("Preparing…")
        self._update_status()
        t = ProcThread(self.q, tag, cmd, cwd, env)
        self.procs[tag] = t
        t.start()
        return True

    def _open_run_log(self, tag: str, cmd):
        LOG_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = LOG_DIR / f"{tag}-{stamp}.log"
        try:
            fh = open(path, "w", encoding="utf-8")
        except OSError:
            return
        try:
            fh.write(f"# {tag} run {stamp}\n# cmd: {' '.join(str(c) for c in cmd)}\n")
            fh.flush()
        except OSError:
            pass
        self._run_log[tag] = (path, fh)
        self._last_log_path[tag] = path

    def _close_run_log(self, tag: str):
        entry = self._run_log.pop(tag, None)
        if entry:
            try:
                entry[1].close()
            except OSError:
                pass

    def _open_log(self, tag: str):
        path = self._last_log_path.get(tag)
        if path and path.exists():
            os.startfile(str(path))  # noqa: S606
        else:
            messagebox.showinfo("No log yet", f"No run log for the {tag} yet.")

    def _stop(self, tag):
        t = self.procs.get(tag)
        if t:
            self._log("system", f"stopping {tag}...", "warn")
            t.stop()

    def _proc_done(self, tag, code):
        if tag not in self.procs:
            return
        thread = self.procs.pop(tag)
        prog = self.gen_prog if tag == "generator" else self.clip_prog
        btn_run = self.gen_run_btn if tag == "generator" else self.clip_run_btn
        btn_stop = self.gen_stop_btn if tag == "generator" else self.clip_stop_btn
        btn_log = self.gen_log_btn if tag == "generator" else self.clip_log_btn
        out_lbl = self.gen_out if tag == "generator" else self.clip_out_lbl
        self._close_run_log(tag)
        btn_log.configure(state="normal")
        if thread.stopped:
            self._log("system", f"{tag} pipeline stopped", "warn")
            prog.stop()
            out_lbl.configure(text="Stopped", foreground=ORANGE)
        elif code != 0:
            err = self._last_error.get(tag, f"exited with code {code}")
            self._log("system", f"{tag} pipeline FAILED: {err}", "err")
            prog.fail("Failed")
            out_lbl.configure(text=f"Failed — {err[:120]}", foreground=RED)
        else:
            self._log("system", f"{tag} pipeline finished", "ok")
            prog.finish()
            if tag == "generator":
                self._refresh_gen_history(select_latest=True)
            else:
                self._refresh_clip_history(select_latest=True)
        btn_run.configure(state="normal")
        btn_stop.configure(state="disabled")
        self._update_status()

    def _update_status(self):
        def name(state, label):
            if state == PipeProgress.RUNNING:
                return label, "running"
            if state == PipeProgress.FAILED:
                return label, "failed"
            if state == PipeProgress.STOPPED:
                return label, "stopped"
            return None, None

        g_state, g_label = name(self.gen_prog.state, "Generator")
        c_state, c_label = name(self.clip_prog.state, "Clipper")
        active = [(a, b) for a, b in ((g_state, g_label), (c_state, c_label)) if a]

        if not active:
            self.status_pill.configure(text="●  Ready", foreground=GREEN)
        else:
            failed = [a for a, b in active if b == "failed"]
            stopped = [a for a, b in active if b == "stopped"]
            running = [a for a, b in active if b == "running"]
            if failed:
                self.status_pill.configure(
                    text=f"●  {', '.join(failed)} failed", foreground=RED)
            elif running:
                label = "2 pipelines running" if len(running) == 2 else f"{running[0]} running"
                self.status_pill.configure(text=f"●  {label}", foreground=YELLOW)
            elif stopped:
                self.status_pill.configure(
                    text=f"●  {', '.join(stopped)} stopped", foreground=ORANGE)

    def run_generator(self):
        cfg = load_gen_config()
        cfg["niche"] = self.niche_txt.get("1.0", "end").strip()
        cfg["audience"] = self.audience_e.get().strip()
        try:
            cfg["script"]["target_seconds"] = int(float(self.seconds_sb.get() or 120))
        except ValueError:
            messagebox.showerror("Invalid length", "Length must be a number (30–180).")
            return
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
        out = Path(self.clip_out.get().strip() or str(CLIP_OUT_DIR))
        cmd = [str(CLIP_PY), "main.py", src, "--mode", "local",
               "--num-clips", str(int(float(self.clip_num.get() or 3))),
               "--aspect-ratio", self.clip_ratio.get()]
        env = _run_env()
        env["LOCAL_MIN_CLIP_DURATION"] = str(int(float(self.clip_min.get() or 30)))
        env["LOCAL_OUTPUT_DIR"] = str(out)
        if self._launch("clipper", cmd, CLIP_DIR, env):
            self._log("ok", f"Clipper started. Output: {out}")

    # ------------------------------------------------------------ results ---
    def _refresh_gen_history(self, select_latest=False):
        base = GEN_OUT_DIR
        self.gen_list.delete(0, "end")
        self._gen_hist = []
        if base.exists():
            dirs = [d for d in base.iterdir() if d.is_dir() and (d / "final.mp4").exists()]
            dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            for d in dirs[:HISTORY_LIMIT]:
                mtime = datetime.fromtimestamp(d.stat().st_mtime)
                label = f"{d.name[:48]:<48}  {mtime:%Y-%m-%d %H:%M}"
                self._gen_hist.append((label, d / "final.mp4"))
                self.gen_list.insert("end", label)
        if not self._gen_hist:
            self.gen_out.configure(text="No videos generated yet", foreground=MUTED)
            return
        idx = 0 if select_latest else -1
        self.gen_list.selection_clear(0, "end")
        self.gen_list.selection_set(idx)
        self.gen_list.see(idx)
        self._apply_gen_selection(idx)

    def _on_gen_select(self, _e=None):
        sel = self.gen_list.curselection()
        if sel:
            self._apply_gen_selection(sel[0])

    def _apply_gen_selection(self, idx):
        if 0 <= idx < len(self._gen_hist):
            _, path = self._gen_hist[idx]
            self._gen_out_path = path
            mtime = datetime.fromtimestamp(path.parent.stat().st_mtime)
            self.gen_out.configure(text=f"final.mp4  ·  {mtime:%Y-%m-%d %H:%M:%S}", foreground=GREEN)
            self.gen_open_btn.configure(state="normal")
            self.gen_copy_btn.configure(state="normal")

    def _refresh_clip_history(self, select_latest=False):
        out = Path(self.clip_out.get().strip() or str(CLIP_OUT_DIR))
        self.clip_list.delete(0, "end")
        self._clip_hist = []
        self._clip_selected: Path | None = None
        if out.exists():
            found: dict[Path, list[Path]] = {}
            for f in out.rglob("short_*.mp4"):
                found.setdefault(f.parent, []).append(f)
            folders = sorted(
                found.items(),
                key=lambda kv: max(p.stat().st_mtime for p in kv[1]),
                reverse=True,
            )
            for folder, files in folders[:HISTORY_LIMIT]:
                mtime = datetime.fromtimestamp(max(p.stat().st_mtime for p in files))
                label = f"{str(folder)[:56]:<56}  {len(files)} shorts  {mtime:%Y-%m-%d %H:%M}"
                self._clip_hist.append((label, folder))
                self.clip_list.insert("end", label)
        if not self._clip_hist:
            self.clip_out_lbl.configure(text="No shorts generated yet", foreground=MUTED)
            return
        idx = 0 if select_latest else -1
        self.clip_list.selection_clear(0, "end")
        self.clip_list.selection_set(idx)
        self.clip_list.see(idx)
        self._apply_clip_selection(idx)

    def _on_clip_select(self, _e=None):
        sel = self.clip_list.curselection()
        if sel:
            self._apply_clip_selection(sel[0])

    def _apply_clip_selection(self, idx):
        if 0 <= idx < len(self._clip_hist):
            _, folder = self._clip_hist[idx]
            self._clip_selected = folder
            n = len(list(folder.glob("short_*.mp4")))
            self.clip_out_lbl.configure(text=f"{folder}  ·  {n} short(s)", foreground=GREEN)
            self.clip_open_btn.configure(state="normal")
            self.clip_copy_btn.configure(state="normal")

    def _open_clip_folder(self):
        if self._clip_selected:
            os.makedirs(self._clip_selected, exist_ok=True)
            os.startfile(str(self._clip_selected))  # noqa: S606

    # ------------------------------------------------------- state save -----
    def _gather_state(self) -> dict:
        def _v(widget, default=""):
            try:
                return widget.get()
            except Exception:
                return default

        return {
            "view": self._view,
            "create": {
                "upload": bool(self.upload_on.get()),
                "publish": _v(self.publish_e, ""),
                "music_on": bool(self.music_on.get()),
                "music_vol": _v(self.music_vol, "15"),
            },
            "clip": {
                "src": _v(self.clip_src, ""),
                "num": _v(self.clip_num, "3"),
                "ratio": _v(self.clip_ratio, "9:16"),
                "min": _v(self.clip_min, "30"),
                "out": _v(self.clip_out, str(CLIP_OUT_DIR)),
            },
            "console_visible": bool(self.console_visible.get()),
        }

    def _save_state(self):
        _write_json(STATE_FILE, self._gather_state())

    def _restore_state(self):
        create = self.state.get("create", {})
        self.upload_on.set(bool(create.get("upload", False)))
        self.publish_e.delete(0, "end")
        self.publish_e.insert(0, create.get("publish", ""))
        if "music_on" in create:
            self.music_on.set(bool(create["music_on"]))
        if "music_vol" in create:
            try:
                self.music_vol.set(int(float(create["music_vol"])))
            except (TypeError, ValueError):
                pass
        clip = self.state.get("clip", {})
        self.clip_src.delete(0, "end")
        self.clip_src.insert(0, clip.get("src", ""))
        if "num" in clip:
            self.clip_num.delete(0, "end")
            self.clip_num.insert(0, clip["num"])
        if "ratio" in clip:
            self.clip_ratio.set(clip["ratio"])
        if "min" in clip:
            self.clip_min.delete(0, "end")
            self.clip_min.insert(0, clip["min"])
        if "out" in clip:
            self.clip_out.delete(0, "end")
            self.clip_out.insert(0, clip["out"])
        if not self.state.get("console_visible", True):
            self._toggle_console()

    def _on_close(self):
        for j in self._jobs:
            try:
                self.after_cancel(j)
            except Exception:
                pass
        for t in list(self.procs.values()):
            t.stop()
        for tag in list(self._run_log):
            self._close_run_log(tag)
        self._save_state()
        self.destroy()


def main():
    app = App()
    if "--selftest" in sys.argv:
        app.after(1500, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
