"""
config.py – Application configuration.
All settings come from .env — nothing is hardcoded here.

Required .env keys
──────────────────
  API_KEY               Your secret key (required by the API server).
                        The Celery worker does NOT need this — it never
                        validates requests, only the FastAPI server does.

Optional .env keys (shown with defaults)
─────────────────────────────────────────
  VOSK_MODEL_PATH       vosk-model-hi-0.22
  PUNCT_MODEL_PATH      (empty = Cadence downloads automatically)
  SAMPLE_RATE           16000
  CHUNK_SIZE            4096
  MAX_UPLOAD_MB         200
  MAX_CONCURRENT        1
  OUTPUT_DIR            outputs
  HOST                  0.0.0.0
  API_PORT              8010
  CORS_ORIGINS          *   (comma-separated list, or * for all)
  REDIS_HOST            localhost
  REDIS_PORT            6379
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ── Paths ──────────────────────────────────────────────────────────────
VOSK_MODEL_PATH  = os.getenv("VOSK_MODEL_PATH",  "vosk-model-hi-0.22")
PUNCT_MODEL_PATH = os.getenv("PUNCT_MODEL_PATH", "")

# ── Auth ───────────────────────────────────────────────────────────────
# NOTE: API_KEY is intentionally NOT validated here at import time.
# If we called sys.exit() here, the Celery worker would crash on startup
# because worker.py imports config too (via celeryconfig.py).
# Validation happens lazily in api.py via validate_api_key_on_startup().
API_KEY = os.getenv("API_KEY", "")

# ── Audio ──────────────────────────────────────────────────────────────
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", 16000))
CHUNK_SIZE  = int(os.getenv("CHUNK_SIZE",  4096))

# ── File handling ──────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"wav", "mp3", "mp4", "mkv", "avi", "flac", "ogg", "webm", "m4a"}
MAX_UPLOAD_MB      = int(os.getenv("MAX_UPLOAD_MB", 200))
MAX_UPLOAD_BYTES   = MAX_UPLOAD_MB * 1024 * 1024
OUTPUT_DIR         = os.getenv("OUTPUT_DIR", "outputs")
DATA_DIR           = os.getenv("DATA_DIR", "data")

# ── Concurrency ────────────────────────────────────────────────────────
# With Celery, /transcribe jobs are handled by workers.
# This semaphore only controls the in-process WebSocket /stream path.
MAX_CONCURRENT_TRANSCRIPTIONS = int(os.getenv("MAX_CONCURRENT", 1))

# ── Redis ──────────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# ── CORS ───────────────────────────────────────────────────────────────
_cors_raw    = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",")] if _cors_raw != "*" else ["*"]

# ── Server ─────────────────────────────────────────────────────────────
HOST     = os.getenv("HOST",     "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", 8010))
PRELOAD_MODELS = os.getenv("PRELOAD_MODELS", "true").lower() in {"1", "true", "yes", "on"}


# ── Runtime directories ────────────────────────────────────────────────
def ensure_dirs() -> None:
    """Create required runtime directories. Called once from api.py lifespan."""
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


# ── API key validation ─────────────────────────────────────────────────
def validate_api_key_on_startup() -> None:
    """
    Called ONLY from api.py lifespan — never at import time.

    This runs in the FastAPI server process only, not in the Celery worker.
    The worker imports config but never needs API_KEY.
    """
    if not API_KEY:
        import sys
        print(
            "\n[CONFIG] FATAL: API_KEY is not set in your .env file.\n"
            "         Add:  API_KEY=<your-secret>  and restart the server.\n",
            file=sys.stderr,
        )
        sys.exit(1)
