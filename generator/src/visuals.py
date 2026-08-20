from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os
import subprocess
import threading
import time
import requests
from .config import PEXELS_API_KEY, CONFIG

API = "https://api.pexels.com/videos/search"
MAX_ATTEMPTS = 2
SEARCH_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 90
PER_SCENE_BUDGET = 45  # hard ceiling per scene before offline placeholder


def search_vertical(query: str, min_duration: float = 3.0) -> str | None:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.get(
                API,
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "orientation": "portrait", "per_page": 15,
                        "size": "medium"},
                timeout=SEARCH_TIMEOUT,
            )
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(2 ** attempt)
    videos = r.json().get("videos", [])
    for v in videos:
        if v.get("duration", 0) < min_duration:
            continue
        files = [f for f in v["video_files"]
                 if f.get("width", 0) >= 1080 and f.get("height", 0) > f.get("width", 0)]
        if not files:
            continue
        files.sort(key=lambda f: f.get("height", 0))
        return files[0]["link"]
    return None


def download(url: str, out_path: Path) -> Path:
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return out_path


def generate_placeholder(index: int, out_path: Path,
                        w: int = 1080, h: int = 1920) -> Path:
    """Animated color-gradient background so the pipeline still completes when
    the Pexels API is slow or unreachable (fully offline)."""
    hue = (index * 47) % 360
    c0 = f"0x{min(255, hue):02X}1828"
    c1 = f"0x{min(255, (hue + 70) % 360):02X}3850"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"gradients=s={w}x{h}:c0={c0}:c1={c1}:nb_colors=2:"
               f"duration=20:speed=0.06:type=linear:seed={index}",
         "-t", "20", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", str(out_path)],
        check=True, capture_output=True, timeout=90,
    )
    return out_path


def _fetch_one(i: int, scene: dict, out_dir: Path, w: int, h: int, total: int) -> Path:
    tmp = out_dir / f"tmp_{i:02d}.mp4"
    done: dict = {}
    final = out_dir / f"scene_{i:02d}.mp4"

    def _dl():
        try:
            url = search_vertical(scene["visual_query"])
            if not url:
                raise RuntimeError("no Pexels result")
            download(url, tmp)
            done["ok"] = True
        except Exception as e:
            done["err"] = e

    t = threading.Thread(target=_dl, daemon=True)
    t.start()
    t.join(timeout=PER_SCENE_BUDGET)

    if t.is_alive():
        print(f"      scene {i + 1}/{total} timed out ({PER_SCENE_BUDGET}s) - offline placeholder",
              flush=True)
    elif "err" in done:
        print(f"      scene {i + 1}/{total} failed ({done['err']}) - offline placeholder",
              flush=True)
    else:
        print(f"      scene {i + 1}/{total} downloaded", flush=True)
        os.replace(tmp, final)
        return final

    t.join(0.2)  # give the thread a moment so it can't write mid-move
    place = generate_placeholder(i, out_dir / f"ph_{i:02d}.mp4", w, h)
    os.replace(place, final)
    return final


def _cleanup_temps(out_dir: Path, total: int):
    for i in range(total):
        tmp = out_dir / f"tmp_{i:02d}.mp4"
        if not tmp.exists():
            continue
        for _ in range(10):  # wait for a late download to release the file
            try:
                tmp.unlink()
                break
            except PermissionError:
                time.sleep(0.5)


def fetch_for_scenes(scenes: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    v = CONFIG.get("video", {})
    w, h = int(v.get("width", 1080)), int(v.get("height", 1920))
    paths: list[Path | None] = [None] * len(scenes)

    # Parallel download: the Pexels API is slow from some networks (15s+ per
    # request), so overlap the per-scene latency with a small worker pool.
    workers = min(4, max(1, len(scenes)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_map = {
            ex.submit(_fetch_one, i, s, out_dir, w, h, len(scenes)): i
            for i, s in enumerate(scenes)
        }
        for fut in as_completed(fut_map):
            i = fut_map[fut]
            paths[i] = fut.result()

    # The abandoned download threads may still hold the temp files open;
    # wait for them to finish (they daemon-exit on process end) and clean up.
    _cleanup_temps(out_dir, len(scenes))
    return paths  # type: ignore[return-value]