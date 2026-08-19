"""Faceless YouTube Automation Studio — tkinter GUI for both pipelines.

Tab 1: Generator  (topic -> script -> voice -> captions -> b-roll -> video)
Tab 2: Clipper    (long video -> viral vertical shorts)
Tab 3: Guide      (step-by-step instructions)

Run from the project root:
    generator\\.venv\\Scripts\\python.exe gui.py

Both pipelines stream their output into a shared console in real time and can
run at the same time.
"""
import os
import queue
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

# ffmpeg location (winget install of Gyan.FFmpeg) — injected onto PATH so the
# pipelines find it even when launched from a fresh terminal.
_FFMPEG_PKG = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
_FFMPEG_DIR = next(
    (_FFMPEG_PKG / p / "ffmpeg-9.0-full_build" / "bin" for p in os.listdir(_FFMPEG_PKG) if p.startswith("Gyan.FFmpeg"))
    if _FFMPEG_PKG.exists() else iter(()), None
)

VOICES = [
    "en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-EricNeural",
    "en-US-JennyNeural", "en-US-AriaNeural", "en-US-MichelleNeural",
    "en-GB-SoniaNeural", "en-GB-RyanNeural",
    "en-AU-WilliamNeural", "en-AU-NatashaNeural",
]
ASPECTS = ["9:16", "1:1", "16:9"]

# ----------------------------------------------------------------------------
# Dark theme palette
# ----------------------------------------------------------------------------
BG = "#0f1117"
PANEL = "#161a23"
PANEL_2 = "#1d2230"
INPUT = "#202635"
FG = "#e5e7eb"
MUTED = "#9aa3b2"
ACCENT = "#6366f1"
ACCENT_HOVER = "#818cf8"
GREEN = "#34d399"
PINK = "#f472b6"
RED = "#f87171"
YELLOW = "#fbbf24"
BORDER = "#2a3142"


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _run_env() -> dict:
    env = dict(os.environ)
    if _FFMPEG_DIR and _FFMPEG_DIR.exists():
        env["PATH"] = str(_FFMPEG_DIR) + os.pathsep + env.get("PATH", "")
    return env


# ----------------------------------------------------------------------------
# Generator config helpers
# ----------------------------------------------------------------------------
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


def load_gen_config() -> dict:
    cfg = json_clone(DEFAULT_GEN)
    try:
        if GEN_CONFIG.exists():
            loaded = yaml.safe_load(GEN_CONFIG.read_text(encoding="utf-8")) or {}
            _deep_merge(cfg, loaded)
    except Exception:
        pass
    return cfg


def json_clone(obj):
    import copy
    return copy.deepcopy(obj)


def _deep_merge(base: dict, extra: dict):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def save_gen_config(cfg: dict):
    GEN_CONFIG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ----------------------------------------------------------------------------
# Proc runner — streams lines into a queue, tagged by tab
# ----------------------------------------------------------------------------
class ProcThread(threading.Thread):
    def __init__(self, q: "queue.Queue", tag: str, cmd, cwd: Path, env=None):
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


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Faceless YouTube Automation Studio")
        self.geometry("1180x820")
        self.minsize(960, 680)
        self.configure(bg=BG)
        self.q: "queue.Queue" = queue.Queue()
        self.procs: dict[str, ProcThread] = {}
        self._build_styles()
        self._build_ui()
        self._poll_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- styles -------------------------------------------------------------
    def _build_styles(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("Card.TFrame", background=PANEL_2)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Panel.TLabel", background=PANEL, foreground=FG)
        st.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        st.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI", 17, "bold"))
        st.configure("Section.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI", 11, "bold"))
        st.configure("CardH.TLabel", background=PANEL_2, foreground=FG, font=("Segoe UI", 11, "bold"))
        st.configure("TButton", background=PANEL_2, foreground=FG, borderwidth=1, focusthickness=0, padding=(12, 7))
        st.map("TButton", background=[("active", ACCENT_HOVER), ("disabled", "#2a2f3a")],
               foreground=[("disabled", MUTED)])
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=("Segoe UI", 10, "bold"))
        st.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#3b3f6e")],
               foreground=[("disabled", "#c7cbf5")])
        st.configure("Danger.TButton", background="#7f1d1d", foreground="#fff", font=("Segoe UI", 10, "bold"))
        st.map("Danger.TButton", background=[("active", "#991b1b"), ("disabled", "#44272b")])
        st.configure("TCheckbutton", background=PANEL, foreground=FG, focuscolor=PANEL)
        st.map("TCheckbutton", background=[("active", PANEL)])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL_2, foreground=MUTED, padding=(18, 9), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL_2, borderwidth=0)
        st.configure("TCheckbutton", background=PANEL)

    def _entry(self, parent, value="", width=38, show=None):
        e = tk.Entry(parent, bg=INPUT, fg=FG, insertbackground=FG, relief="flat",
                     font=("Segoe UI", 10), width=width, show=show,
                     highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        e.insert(0, value)
        return e

    def _label(self, parent, text, style="Panel.TLabel"):
        return ttk.Label(parent, text=text, style=style)

    # -- UI -----------------------------------------------------------------
    def _build_ui(self):
        self._header()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=(6, 0))
        self._gen_tab = ttk.Frame(nb)
        self._clip_tab = ttk.Frame(nb)
        self._guide_tab = ttk.Frame(nb)
        nb.add(self._gen_tab, text="   Generator   ")
        nb.add(self._clip_tab, text="   Clipper   ")
        nb.add(self._guide_tab, text="   Guide   ")
        self._build_generator(nb)
        self._build_clipper(nb)
        self._build_guide(nb)
        self._build_console()
        self._status_bar()

    def _header(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=16, pady=(14, 2))
        ttk.Label(head, text="Faceless YouTube Automation Studio", style="Title.TLabel").pack(side="left")
        ver = ttk.Label(head, text="generator + clipper  |  NVIDIA NIM  |  local Whisper", style="Muted.TLabel")
        ver.configure(background=BG)
        ver.pack(side="right")

    def _card(self, parent, title):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", padx=12, pady=8)
        ttk.Label(card, text=title, style="CardH.TLabel").pack(anchor="w", padx=12, pady=(10, 6))
        return card

    def _build_generator(self, nb):
        wrap = ttk.Frame(nb)
        wrap.pack(fill="both", expand=True)
        body = ttk.Frame(wrap, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        cfg = load_gen_config()

        card = self._card(body, "Content")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x", padx=12, pady=4)
        self._label(row, "Niche", "Muted.TLabel").pack(anchor="w")
        self.niche_txt = tk.Text(row, height=3, bg=INPUT, fg=FG, insertbackground=FG, relief="flat",
                                 font=("Segoe UI", 10), highlightthickness=1,
                                 highlightbackground=BORDER, highlightcolor=ACCENT)
        self.niche_txt.insert("1.0", cfg["niche"])
        self.niche_txt.pack(fill="x", pady=(3, 8))
        row2 = ttk.Frame(card, style="Card.TFrame"); row2.pack(fill="x", padx=12, pady=4)
        self._label(row2, "Audience", "Muted.TLabel").pack(anchor="w")
        self.audience_e = self._entry(row2, cfg["audience"])
        self.audience_e.pack(fill="x", pady=(3, 8))

        card = self._card(body, "Script & Voice")
        grid = ttk.Frame(card, style="Card.TFrame"); grid.pack(fill="x", padx=12, pady=4)
        grid.columnconfigure((0, 1, 2, 3), weight=1)
        self._label(grid, "Target length (seconds)", "Muted.TLabel").grid(row=0, column=0, sticky="w")
        self._label(grid, "Voice", "Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self._label(grid, "Music volume", "Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.seconds_sb = tk.Spinbox(grid, from_=30, to=180, width=8,
                                     bg=INPUT, fg=FG, insertbackground=FG,
                                     buttonbackground=PANEL_2, relief="flat",
                                     highlightthickness=1, highlightbackground=BORDER,
                                     highlightcolor=ACCENT)
        self.seconds_sb.delete(0, "end")
        self.seconds_sb.insert(0, cfg["script"]["target_seconds"])
        self.seconds_sb.grid(row=1, column=0, sticky="w", pady=(3, 8))
        self.voice_cb = ttk.Combobox(grid, values=VOICES, width=24, state="readonly")
        self.voice_cb.set(cfg["voice"]["voice"])
        self.voice_cb.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(3, 8))
        self.music_vol = ttk.Scale(grid, from_=0, to=50, orient="horizontal",
                                   command=lambda _v: self._sync_music_vol())
        self.music_vol.set(int(cfg["music"]["volume"] * 100))
        self.music_vol.grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(3, 0))
        self.music_vol_lbl = ttk.Label(grid, text=f"{int(cfg['music']['volume'] * 100)}%", style="Muted.TLabel")
        self.music_vol_lbl.grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(3, 0))
        self.music_on = tk.BooleanVar(value=cfg["music"]["enabled"])
        ttk.Checkbutton(grid, text="Add background music", variable=self.music_on,
                        style="TCheckbutton").grid(row=2, column=0, sticky="w")

        card = self._card(body, "Publishing")
        self.upload_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(card, text="Upload to YouTube after building (requires OAuth setup)",
                        variable=self.upload_on, style="TCheckbutton").pack(anchor="w", padx=12, pady=(4, 2))
        prow = ttk.Frame(card, style="Card.TFrame"); prow.pack(fill="x", padx=12, pady=(0, 10))
        self._label(prow, "Publish at (optional, ISO UTC, e.g. 2026-08-20T14:00:00Z)", "Muted.TLabel").pack(side="left")
        self.publish_e = self._entry(prow, "", width=32)
        self.publish_e.pack(side="left", padx=(10, 0))

        btns = ttk.Frame(body, style="Panel.TFrame"); btns.pack(fill="x", padx=12, pady=(6, 10))
        self.gen_run_btn = ttk.Button(btns, text="Generate Video", style="Accent.TButton",
                                      command=self.run_generator)
        self.gen_run_btn.pack(side="left")
        self.gen_stop_btn = ttk.Button(btns, text="Stop", style="Danger.TButton", state="disabled",
                                       command=lambda: self._stop("generator"))
        self.gen_stop_btn.pack(side="left", padx=(10, 0))
        ttk.Button(btns, text="Open Output Folder", command=lambda: self._open_output(GEN_DIR / "output")).pack(side="left", padx=(10, 0))
        self.gen_bar = ttk.Progressbar(btns, mode="indeterminate", length=180)
        self.gen_bar.pack(side="right", pady=4)

    def _sync_music_vol(self):
        if getattr(self, "music_vol_lbl", None) is not None:
            self.music_vol_lbl.configure(text=f"{int(float(self.music_vol.get()))}%")

    def _build_clipper(self, nb):
        wrap = ttk.Frame(nb)
        wrap.pack(fill="both", expand=True)
        body = ttk.Frame(wrap, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        card = self._card(body, "Source Video")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x", padx=12, pady=(4, 10))
        self.clip_src = self._entry(row, "", width=56)
        self.clip_src.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse_clip_src).pack(side="left", padx=(8, 0))

        card = self._card(body, "Shorts")
        grid = ttk.Frame(card, style="Card.TFrame"); grid.pack(fill="x", padx=12, pady=4)
        grid.columnconfigure((0, 1, 2), weight=1)
        self._label(grid, "Number of clips", "Muted.TLabel").grid(row=0, column=0, sticky="w")
        self._label(grid, "Aspect ratio", "Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self._label(grid, "Min clip length (s)", "Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.clip_num = tk.Spinbox(grid, from_=1, to=8, width=8, bg=INPUT, fg=FG,
                                   insertbackground=FG, buttonbackground=PANEL_2,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, highlightcolor=ACCENT)
        self.clip_num.delete(0, "end")
        self.clip_num.insert(0, 3)
        self.clip_num.grid(row=1, column=0, sticky="w", pady=(3, 8))
        self.clip_ratio = ttk.Combobox(grid, values=ASPECTS, width=10, state="readonly")
        self.clip_ratio.set("9:16")
        self.clip_ratio.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(3, 8))
        self.clip_min = tk.Spinbox(grid, from_=10, to=120, width=8, bg=INPUT, fg=FG,
                                   insertbackground=FG, buttonbackground=PANEL_2,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, highlightcolor=ACCENT)
        self.clip_min.delete(0, "end")
        self.clip_min.insert(0, 30)
        self.clip_min.grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(3, 8))

        card = self._card(body, "Output")
        orow = ttk.Frame(card, style="Card.TFrame"); orow.pack(fill="x", padx=12, pady=(4, 10))
        self.clip_out = self._entry(orow, str(CLIP_DIR / "output"), width=56)
        self.clip_out.pack(side="left", fill="x", expand=True)
        ttk.Button(orow, text="Browse...", command=self._browse_clip_out).pack(side="left", padx=(8, 0))

        btns = ttk.Frame(body, style="Panel.TFrame"); btns.pack(fill="x", padx=12, pady=(6, 10))
        self.clip_run_btn = ttk.Button(btns, text="Clip Video", style="Accent.TButton",
                                       command=self.run_clipper)
        self.clip_run_btn.pack(side="left")
        self.clip_stop_btn = ttk.Button(btns, text="Stop", style="Danger.TButton", state="disabled",
                                        command=lambda: self._stop("clipper"))
        self.clip_stop_btn.pack(side="left", padx=(10, 0))
        ttk.Button(btns, text="Open Output Folder", command=self._open_output).pack(side="left", padx=(10, 0))
        self.clip_bar = ttk.Progressbar(btns, mode="indeterminate", length=180)
        self.clip_bar.pack(side="right", pady=4)

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
        if default is not None:
            target = default
        else:
            target = Path(self.clip_out.get()).resolve() if self.clip_out.get() else CLIP_DIR / "output"
        os.makedirs(target, exist_ok=True)
        os.startfile(str(target))  # noqa: S606  (Windows)

    def _build_guide(self, nb):
        wrap = ttk.Frame(nb)
        wrap.pack(fill="both", expand=True)
        txt = tk.Text(wrap, bg=PANEL, fg=FG, wrap="word", relief="flat", font=("Consolas", 10),
                      padx=18, pady=14, insertbackground=FG)
        sb = ttk.Scrollbar(wrap, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.configure(state="disabled")
        guide = (
            "STEP-BY-STEP GUIDE\n"
            "==================\n"
            "\n"
            "1. ONE-TIME SETUP\n"
            "   - Install ffmpeg (done for you):  winget install Gyan.FFmpeg\n"
            "   - Python is managed by uv; both venvs already exist.\n"
            "   - API keys live in .env files (git-ignored, never commit):\n"
            "       generator\\.env   -> LLM_API_KEY (NVIDIA nvapi-...), PEXELS_API_KEY\n"
            "       clipper\\.env     -> NVIDIA_API_KEY, LLM_PROVIDER=nvidia\n"
            "   - Get a free NVIDIA key at https://build.nvidia.com (NVAIE -> API)\n"
            "   - Get a free Pexels key at https://www.pexels.com/api/\n"
            "\n"
            "2. GENERATOR TAB  (make a faceless video from scratch)\n"
            "   a. Set your Niche and Audience (e.g. Japanese culture / food).\n"
            "   b. Pick target length, voice, and music volume.\n"
            "   c. Press 'Generate Video'. Stages run automatically:\n"
            "        script (NVIDIA LLM) -> voiceover (edge-tts)\n"
            "        -> word-timed captions (local Whisper)\n"
            "        -> b-roll (Pexels) -> ffmpeg assemble + music bed\n"
            "   d. Output: generator\\output\\<timestamp>_<topic>\\final.mp4\n"
            "   e. First YouTube upload needs OAuth once:\n"
            "        generator\\.venv\\Scripts\\python.exe -m src.authorize\n"
            "      then tick 'Upload to YouTube' in the app.\n"
            "\n"
            "3. CLIPPER TAB  (chop a long video into vertical shorts)\n"
            "   a. Source: paste a YouTube URL or a local file path (or Browse).\n"
            "   b. Choose how many clips, aspect ratio (9:16 = Shorts/Reels), and\n"
            "      minimum clip length so shorts are never too short.\n"
            "   c. Press 'Clip Video'. Pipeline:\n"
            "        download/read -> Whisper transcript -> NVIDIA ranks highlights\n"
            "        -> face-tracked 9:16 crop -> captions -> shorts\\.mp4 files\n"
            "   d. Output: clipper\\output\\short_01.mp4, short_02.mp4, ...\n"
            "\n"
            "4. RUNNING BOTH\n"
            "   - They run independently and can be started at the same time.\n"
            "   - Watch progress in the console at the bottom; errors appear in red.\n"
            "\n"
            "5. TWEAKS\n"
            "   - generator\\config.yaml : niche, length, voice, music, captions.\n"
            "   - clipper\\.env : LOCAL_MIN_CLIP_DURATION, LOCAL_WHISPER_MODEL.\n"
            "\n"
            "6. COSTS  (all free tiers)\n"
            "   - NVIDIA NIM: free (rate-limited, ~1-2 min/call when queued)\n"
            "   - edge-tts voiceover: free   |   Whisper: local CPU, free\n"
            "   - Pexels b-roll: free        |   YouTube API: free quota\n"
        )
        txt.configure(state="normal")
        txt.insert("1.0", guide)
        txt.configure(state="disabled")

    def _build_console(self):
        wrap = ttk.Frame(self, style="Panel.TFrame")
        wrap.pack(fill="both", padx=14, pady=(10, 4))
        head = ttk.Frame(wrap, style="Panel.TFrame")
        head.pack(fill="x", padx=4, pady=(2, 0))
        ttk.Label(head, text="Console", style="Section.TLabel").pack(side="left")
        ttk.Button(head, text="Clear", style="TButton", command=self._clear_console).pack(side="right")
        self.console = tk.Text(wrap, bg="#0b0d12", fg=MUTED, wrap="word", relief="flat",
                               font=("Consolas", 9), height=12, state="disabled",
                               insertbackground=FG, padx=8, pady=6)
        sb = ttk.Scrollbar(wrap, command=self.console.yview)
        self.console.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)
        for tag, color in (("gen", GREEN), ("clip", PINK), ("sys", ACCENT),
                           ("err", RED), ("warn", YELLOW), ("ok", GREEN)):
            self.console.tag_configure(tag, foreground=color)

    def _status_bar(self):
        self.status = ttk.Label(self, text="Ready", style="Muted.TLabel", anchor="w")
        self.status.pack(fill="x", padx=16, pady=(0, 8))

    # -- log ----------------------------------------------------------------
    def _log(self, tag, line, level="sys"):
        ts = _now()
        color_tag = level if level in ("gen", "clip", "sys", "err", "warn", "ok") else "sys"
        self.console.configure(state="normal")
        self.console.insert("end", f"{ts}  [{tag}] {line}\n", (color_tag,))
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

    def _poll_queue(self):
        try:
            while True:
                tag, line = self.q.get_nowait()
                if line is None:
                    self._proc_done(tag)
                    continue
                self._log(tag, line, self._detect_level(line))
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _proc_done(self, tag):
        if tag not in self.procs:
            return
        self.procs.pop(tag)
        self._log("system", f"{tag} pipeline finished", "sys")
        if tag == "generator":
            self.gen_bar.stop()
            self.gen_run_btn.configure(state="normal")
            self.gen_stop_btn.configure(state="disabled")
        elif tag == "clipper":
            self.clip_bar.stop()
            self.clip_run_btn.configure(state="normal")
            self.clip_stop_btn.configure(state="disabled")
        self.status.configure(text="Ready")

    # -- runners ------------------------------------------------------------
    def _launch(self, tag, cmd, cwd, env=None):
        if tag in self.procs:
            messagebox.showwarning("Already running", f"The {tag} is already running.")
            return False
        self._log("system", f"launching {tag}: {' '.join(str(c) for c in cmd)}", "sys")
        self.status.configure(text=f"{tag} running...")
        if tag == "generator":
            self.gen_run_btn.configure(state="disabled")
            self.gen_stop_btn.configure(state="normal")
            self.gen_bar.start(12)
        else:
            self.clip_run_btn.configure(state="disabled")
            self.clip_stop_btn.configure(state="normal")
            self.clip_bar.start(12)
        thread = ProcThread(self.q, tag, cmd, cwd, env)
        self.procs[tag] = thread
        thread.start()
        return True

    def _stop(self, tag):
        t = self.procs.get(tag)
        if t:
            self._log("system", f"stopping {tag}...", "warn")
            t.stop()

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
        if not self._launch("generator", cmd, GEN_DIR, _run_env()):
            return
        self._log("ok", "Generator config saved. Building full video with music...")

    def run_clipper(self):
        src = self.clip_src.get().strip()
        if not src:
            messagebox.showerror("Missing source", "Enter a YouTube URL or choose a local video file.")
            return
        out = Path(self.clip_out.get().strip() or str(CLIP_DIR / "output"))
        cmd = [
            str(CLIP_PY), "main.py", src,
            "--mode", "local",
            "--num-clips", str(int(float(self.clip_num.get() or 3))),
            "--aspect-ratio", self.clip_ratio.get(),
        ]
        env = _run_env()
        env["LOCAL_MIN_CLIP_DURATION"] = str(int(float(self.clip_min.get() or 30)))
        env["LOCAL_OUTPUT_DIR"] = str(out)
        if not self._launch("clipper", cmd, CLIP_DIR, env):
            return
        self._log("ok", f"Clipper started. Output: {out}")

    def _on_close(self):
        for t in list(self.procs.values()):
            t.stop()
        self.destroy()


def main():
    app = App()
    if "--selftest" in sys.argv:
        app.after(1200, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    import sys
    main()
