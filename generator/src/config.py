import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

# Trust the OS certificate store so HTTPS works behind antivirus / proxy
# TLS interception (which uses a custom root cert that certifi doesn't ship).
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
STATE_FILE = ROOT / "state.json"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or GROQ_API_KEY
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
PEXELS_API_KEY = os.environ["PEXELS_API_KEY"]

LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))
LLM_RETRIES = int(os.environ.get("LLM_RETRIES", "0"))


def llm_providers() -> list[dict]:
    """Ordered list of LLM providers to try.

    Default (`auto`) uses ONLY the configured primary (NVIDIA NIM) so a stale
    extra key never poisons a run. Set LLM_PROVIDER=xai|groq|deepseek|primary to
    pin a provider, or LLM_PROVIDER=all to add the fast xAI/Groq/DeepSeek
    alternatives as fallbacks when their keys are present.
    """
    order = str(os.environ.get("LLM_PROVIDER", "auto")).lower()

    def want(name: str) -> bool:
        if order == "all":
            return True
        if order == "auto":
            return name == "primary"
        return order == name

    provs: list[dict] = []
    if want("primary") and LLM_API_KEY and LLM_BASE_URL:
        provs.append({
            "name": "NVIDIA NIM",
            "base_url": LLM_BASE_URL,
            "api_key": LLM_API_KEY,
            "model": CONFIG["script"]["model"],
        })
    xai = os.environ.get("XAI_API_KEY", "")
    if want("xai") and xai:
        provs.append({
            "name": "xAI",
            "base_url": os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1"),
            "api_key": xai,
            "model": os.environ.get("XAI_MODEL", "grok-3-mini-fast"),
        })
    if want("groq") and GROQ_API_KEY:
        provs.append({
            "name": "Groq",
            "base_url": os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            "api_key": GROQ_API_KEY,
            "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        })
    if want("deepseek") and os.environ.get("DEEPSEEK_API_KEY", ""):
        provs.append({
            "name": "DeepSeek",
            "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "api_key": os.environ["DEEPSEEK_API_KEY"],
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        })
    return provs
