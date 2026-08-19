import asyncio
from pathlib import Path
import edge_tts
from .config import CONFIG


def synth(text: str, out_path: Path) -> Path:
    v = CONFIG["voice"]

    async def _go():
        com = edge_tts.Communicate(
            text,
            voice=v["voice"],
            rate=v.get("rate", "+0%"),
            pitch=v.get("pitch", "+0Hz"),
        )
        await com.save(str(out_path))

    asyncio.run(_go())
    return out_path
