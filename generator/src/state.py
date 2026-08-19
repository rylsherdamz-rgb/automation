import json
from .config import STATE_FILE


def load():
    if not STATE_FILE.exists():
        return {"used_topics": [], "published": []}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def add_topic(topic: str):
    s = load()
    s["used_topics"].append(topic)
    save(s)


def add_published(entry: dict):
    s = load()
    s["published"].append(entry)
    save(s)
