import json
import re
from openai import OpenAI
from .config import LLM_API_KEY, LLM_BASE_URL, CONFIG
from . import state

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

SYSTEM = """You write viral YouTube Shorts scripts for a faceless educational facts channel.

Hard rules:
- The script must run ~{target_seconds} seconds spoken at ~{wps} words/second (target ~{target_words} words total).
- Start with a strong 1-sentence HOOK that creates curiosity in <3 seconds. No "Hey guys" or channel intros.
- Body: {scene_count} surprising, accurate, verifiable facts that build on the hook. One fact per scene.
- End with a 1-sentence CTA: "Follow for more" variant.
- Plain spoken English. No emojis or formatting in the spoken text. No "in this video" meta-talk.
- Each scene's visual_query is 2-4 English nouns that will return relevant b-roll on Pexels (e.g. "octopus swimming ocean", "ancient pyramid desert"). Never include the channel topic word if it has no stock footage (e.g. "dopamine" -> "brain mri neuron").

Return ONLY valid JSON, no prose, no code fences. Schema:
{{
  "topic": "short slug of the topic",
  "title": "YouTube title under 95 chars, must include #shorts",
  "description": "2-3 sentence YouTube description ending with relevant hashtags",
  "tags": ["8-12 lowercase tags"],
  "scenes": [
    {{"text": "spoken sentence", "visual_query": "2-4 stock-footage nouns"}}
  ]
}}"""


def _system_prompt():
    s = CONFIG["script"]
    target_words = int(s["target_seconds"] * s["words_per_second"])
    scene_count = max(5, round(s["target_seconds"] / 10))
    return SYSTEM.format(
        target_seconds=s["target_seconds"],
        wps=s["words_per_second"],
        target_words=target_words,
        scene_count=scene_count,
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def generate():
    used = state.load()["used_topics"]
    avoid = ("\n\nAlready covered (pick something different): "
             + ", ".join(used[-50:])) if used else ""

    user_msg = (
        f"Niche: {CONFIG['niche']}\n"
        f"Audience: {CONFIG['audience']}\n"
        f"Generate ONE fresh Short now.{avoid}"
    )

    resp = client.chat.completions.create(
        model=CONFIG["script"]["model"],
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = resp.choices[0].message.content
    data = _extract_json(raw)
    data["full_text"] = " ".join(s["text"] for s in data["scenes"])
    return data
