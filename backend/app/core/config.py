"""Central configuration for the AgentConnect backend."""
from pathlib import Path
import os

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "data" / "agentconnect.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"

# Local Windows/Linux runs load backend/.env before the API or worker builds adapters.
# Existing process variables win; deployment Compose injects its own environment.
load_dotenv(BACKEND_DIR / ".env", override=False)


def get_database_url() -> str:
    url = os.getenv("AGENTCONNECT_DATABASE_URL", DEFAULT_DATABASE_URL)
    if url.startswith("sqlite:///./"):
        return f"sqlite:///{(BACKEND_DIR / url[12:]).as_posix()}"
    return url


def get_relevance_threshold() -> float:
    return min(1.0, max(0.0, float(os.getenv("AGENTCONNECT_RELEVANCE_THRESHOLD", "0.25"))))


def get_relevance_top_k() -> int:
    return max(0, int(os.getenv("AGENTCONNECT_RELEVANCE_TOP_K", "5")))


def get_relevance_deterministic_weight() -> float:
    return max(0.0, float(os.getenv("AGENTCONNECT_RELEVANCE_DETERMINISTIC_WEIGHT", "0.60")))


def get_relevance_semantic_weight() -> float:
    return max(0.0, float(os.getenv("AGENTCONNECT_RELEVANCE_SEMANTIC_WEIGHT", "0.40")))


def get_relevance_semantic_match_threshold() -> float:
    return min(1.0, max(0.0, float(os.getenv("AGENTCONNECT_RELEVANCE_SEMANTIC_MATCH_THRESHOLD", "0.20"))))


def get_embedding_model_name() -> str:
    return os.getenv("AGENTCONNECT_EMBEDDING_MODEL", "all-MiniLM-L6-v2").strip() or "all-MiniLM-L6-v2"


def is_semantic_relevance_enabled() -> bool:
    return os.getenv("AGENTCONNECT_SEMANTIC_RELEVANCE_ENABLED", "true").strip().lower() not in {"false", "0", "no"}


def get_embedding_provider_name() -> str:
    return os.getenv("AGENTCONNECT_EMBEDDING_PROVIDER", "auto").strip().lower()


def get_gemini_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key or None


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def get_gemini_timeout_seconds() -> float:
    return min(60.0, max(1.0, float(os.getenv("GEMINI_TIMEOUT_SECONDS", "15"))))
