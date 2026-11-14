"""Central configuration for the AgentConnect backend."""
from pathlib import Path
import os

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "data" / "agentconnect.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


def get_database_url() -> str:
    return os.getenv("AGENTCONNECT_DATABASE_URL", DEFAULT_DATABASE_URL)


def get_relevance_threshold() -> float:
    return min(1.0, max(0.0, float(os.getenv("AGENTCONNECT_RELEVANCE_THRESHOLD", "0.25"))))


def get_relevance_top_k() -> int:
    return max(0, int(os.getenv("AGENTCONNECT_RELEVANCE_TOP_K", "5")))


def get_gemini_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key or None


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def get_gemini_timeout_seconds() -> float:
    return min(60.0, max(1.0, float(os.getenv("GEMINI_TIMEOUT_SECONDS", "15"))))
