import json
import re
from openai import OpenAI
from .config import LLM_API_KEY, LLM_BASE_URL, CONFIG
from .upload import get_service

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

CLASSIFY_SYSTEM = """You moderate comments on a faceless educational facts YouTube Shorts channel.

For each comment, decide an action:
- "delete": obvious spam (sub-for-sub, scams, link bait, slurs, off-topic promotion).
- "reply": a sincere question or interesting remark worth a 1-sentence friendly reply.
- "ignore": everything else (emoji, generic praise, neutral comments).

Reply text must be 1 short sentence, no emojis, friendly, never asks for subs.

Return ONLY a JSON object with a "results" array, one object per input comment in order:
{"results": [{"action": "delete|reply|ignore", "reply": "text or empty string"}]}"""


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def list_recent_comments(yt, video_id: str, max_results: int = 50):
    resp = yt.commentThreads().list(
        part="snippet", videoId=video_id, maxResults=max_results, order="time",
        textFormat="plainText",
    ).execute()
    items = []
    for thr in resp.get("items", []):
        top = thr["snippet"]["topLevelComment"]
        items.append({
            "id": top["id"],
            "thread_id": thr["id"],
            "author": top["snippet"]["authorDisplayName"],
            "text": top["snippet"]["textDisplay"],
        })
    return items


def classify(comments: list[dict]) -> list[dict]:
    if not comments:
        return []
    user_msg = "\n".join(f"{i+1}. {c['text']}" for i, c in enumerate(comments))
    resp = client.chat.completions.create(
        model=CONFIG["comments"].get("model", "gpt-4o-mini"),
        max_tokens=2000,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    data = _extract_json(resp.choices[0].message.content)
    return data.get("results", [])


def moderate_video(video_id: str):
    yt = get_service()
    cfg = CONFIG["comments"]
    comments = list_recent_comments(yt, video_id)
    if not comments:
        return {"checked": 0}

    actions = classify(comments)
    deleted = replied = 0
    for c, a in zip(comments, actions):
        act = a.get("action", "ignore")
        if act == "delete" and cfg["delete_spam"]:
            try:
                yt.comments().setModerationStatus(id=c["id"], moderationStatus="rejected").execute()
                deleted += 1
            except Exception:
                pass
        elif act == "reply" and cfg["auto_reply"] and a.get("reply"):
            try:
                yt.comments().insert(
                    part="snippet",
                    body={"snippet": {"parentId": c["id"], "textOriginal": a["reply"]}},
                ).execute()
                replied += 1
            except Exception:
                pass
    return {"checked": len(comments), "deleted": deleted, "replied": replied}
