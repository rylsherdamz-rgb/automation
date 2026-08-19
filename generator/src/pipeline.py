import argparse
import re
import time
from datetime import datetime
from . import script, voice, captions, visuals, assemble, upload, state
from .config import OUTPUT_DIR


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "short"


def run_once(publish_at: str | None = None, upload_to_youtube: bool = True) -> dict:
    print("[1/7] Generating script with Groq")
    data = script.generate()
    print(f"      topic: {data['topic']}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = OUTPUT_DIR / f"{stamp}_{slug(data['topic'])}"
    work.mkdir(parents=True, exist_ok=True)

    print("[2/7] Synthesizing voiceover")
    voice_mp3 = voice.synth(data["full_text"], work / "voice.mp3")

    print("[3/7] Transcribing for word-level captions")
    words = captions.transcribe_words(voice_mp3)

    print("[4/7] Fetching b-roll from Pexels")
    scene_videos = visuals.fetch_for_scenes(data["scenes"], work / "broll")

    print("[5/7] Writing caption file")
    from .config import CONFIG as CFG
    ass_path = captions.write_ass(words, work / "captions.ass",
                                  CFG["video"]["width"], CFG["video"]["height"])

    print("[6/7] Assembling final video with ffmpeg")
    final = assemble.build(
        scene_videos=scene_videos,
        voice_audio=voice_mp3,
        captions_ass=ass_path,
        words=words,
        scenes=data["scenes"],
        out_path=work / "final.mp4",
        work_dir=work / "ffmpeg",
    )
    print(f"      output: {final}")

    video_id = None
    if upload_to_youtube:
        print("[7/7] Uploading to YouTube")
        video_id = upload.upload_video(
            video_path=final,
            title=data["title"],
            description=data["description"],
            tags=data["tags"],
            publish_at=publish_at,
        )
        print(f"      video_id: {video_id} -> https://youtube.com/shorts/{video_id}")

    state.add_topic(data["topic"])
    state.add_published({
        "ts": stamp,
        "topic": data["topic"],
        "title": data["title"],
        "path": str(final),
        "video_id": video_id,
        "publish_at": publish_at,
    })
    return {"video_id": video_id, "path": str(final), "topic": data["topic"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-upload", action="store_true", help="Build only, don't upload")
    p.add_argument("--publish-at", default=None,
                   help="ISO8601 UTC timestamp for scheduled publish, e.g. 2026-05-20T14:00:00Z")
    args = p.parse_args()
    run_once(publish_at=args.publish_at, upload_to_youtube=not args.no_upload)

    print("\n" + "-" * 60)
    print("Done. If FreeFaceless saved you time:")
    print("  Star it:     https://github.com/nils44344/FreeFaceless")
    print("  Niche packs: https://nilaykabariya.gumroad.com/l/wkgohx")
    print("-" * 60)


if __name__ == "__main__":
    main()
