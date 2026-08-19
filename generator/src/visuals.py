from pathlib import Path
import time
import requests
from .config import PEXELS_API_KEY

API = "https://api.pexels.com/videos/search"
MAX_ATTEMPTS = 3


def search_vertical(query: str, min_duration: float = 3.0) -> str | None:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.get(
                API,
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "orientation": "portrait", "per_page": 15, "size": "medium"},
                timeout=60,
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
        files = [f for f in v["video_files"] if f.get("width", 0) >= 1080 and f.get("height", 0) > f.get("width", 0)]
        if not files:
            continue
        files.sort(key=lambda f: f.get("height", 0))
        return files[0]["link"]
    return None


def download(url: str, out_path: Path) -> Path:
    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return out_path
        except requests.RequestException as e:
            last_err = e
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to download {url} after {MAX_ATTEMPTS} attempts: {last_err}")


def fetch_for_scenes(scenes: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, scene in enumerate(scenes):
        url = search_vertical(scene["visual_query"])
        if url is None:
            url = search_vertical("abstract background")
        if url is None:
            raise RuntimeError(f"No Pexels result for scene {i}: {scene['visual_query']}")
        paths.append(download(url, out_dir / f"scene_{i:02d}.mp4"))
    return paths
