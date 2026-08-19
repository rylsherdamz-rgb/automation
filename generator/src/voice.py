import asyncio
import time
from pathlib import Path
import edge_tts
from .config import CONFIG

MAX_ATTEMPTS = 4


def synth(text: str, out_path: Path) -> Path:
    v = CONFIG["voice"]
    last_err: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)

            async def _go():
                com = edge_tts.Communicate(
                    text,
                    voice=v["voice"],
                    rate=v.get("rate", "+0%"),
                    pitch=v.get("pitch", "+0Hz"),
                )
                await com.save(str(out_path))

            asyncio.run(_go())

            if out_path.exists() and out_path.stat().st_size > 0:
                print(f"      voiceover ready: {out_path.stat().st_size} bytes", flush=True)
                return out_path
            print(f"[voice] empty output on attempt {attempt}/{MAX_ATTEMPTS}; retrying", flush=True)
            last_err = RuntimeError("edge-tts returned an empty file")
        except Exception as e:  # network / service hiccups are common with edge-tts
            last_err = e
            print(f"[voice] attempt {attempt}/{MAX_ATTEMPTS} failed: {e}", flush=True)
        time.sleep(2 * attempt)

    raise RuntimeError(
        f"voice synthesis failed after {MAX_ATTEMPTS} attempts: {last_err}"
    )