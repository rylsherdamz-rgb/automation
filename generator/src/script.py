import json
import re
import time
from openai import OpenAI
from .config import LLM_TIMEOUT, LLM_RETRIES, llm_providers, CONFIG
from . import state

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

    providers = llm_providers()
    if not providers:
        raise RuntimeError("no LLM provider configured — set LLM_API_KEY in generator/.env")
    last_err: Exception | None = None

    for prov in providers:
        client = OpenAI(api_key=prov["api_key"], base_url=prov["base_url"],
                        timeout=LLM_TIMEOUT, max_retries=0)  # we handle retries below
        for attempt in range(LLM_RETRIES + 1):
            try:
                resp = client.chat.completions.create(
                    model=prov["model"],
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": _system_prompt()},
                        {"role": "user", "content": user_msg},
                    ],
                )
                print(f"      script provider: {prov['name']} ({prov['model']})", flush=True)
                raw = resp.choices[0].message.content
                data = _extract_json(raw)
                data["full_text"] = " ".join(s["text"] for s in data["scenes"])
                return data
            except Exception as e:
                last_err = e
                code = getattr(e, "status_code", None)
                retryable = (
                    code in (429, 500, 502, 503, 504)
                    or "timed out" in str(e).lower()
                    or isinstance(e, TimeoutError)
                )
                if attempt < LLM_RETRIES and retryable:
                    wait = min(60, 10 * (2 ** attempt))  # 10s, 20s, 40s backoff
                    print(f"[script] {prov['name']} {code or type(e).__name__}; "
                          f"retrying in {wait}s ({attempt + 1}/{LLM_RETRIES})", flush=True)
                    time.sleep(wait)
                else:
                    print(f"[script] provider {prov['name']} failed: {e}", flush=True)
                    break

    raise RuntimeError(f"all LLM providers failed: {last_err}")
