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
