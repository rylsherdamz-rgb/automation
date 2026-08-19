from . import state, comments


def main():
    s = state.load()
    recent = [p for p in s["published"] if p.get("video_id")][-20:]
    total = {"checked": 0, "deleted": 0, "replied": 0}
    for entry in recent:
        try:
            r = comments.moderate_video(entry["video_id"])
            print(f"{entry['video_id']}: {r}")
            for k, v in r.items():
                if isinstance(v, int):
                    total[k] = total.get(k, 0) + v
        except Exception as e:
            print(f"{entry['video_id']}: error {e}")
    print(f"TOTAL: {total}")


if __name__ == "__main__":
    main()
