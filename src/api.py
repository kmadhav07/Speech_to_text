"""
api.py – FastAPI application setup only.

All endpoints live in endpoints.py.

Run with:
    uvicorn api:app --host 0.0.0.0 --port 8010 --reload
"""

import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from pathlib import Path

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import src.config as config
from src.transcribe import preload_all_models
from src.endpoints import router


# ════════════════════════════════════════════════
# Logging
# ════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hindi_stt")
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ════════════════════════════════════════════════
# Readiness flag
# ════════════════════════════════════════════════

_models_ready = False
_startup_error: str | None = None


# ════════════════════════════════════════════════
# Lifespan
# ════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _models_ready, _startup_error

    config.validate_api_key_on_startup()
    config.ensure_dirs()

    logger.info("━" * 60)
    logger.info("  Hindi Speech-to-Text API  |  Starting up")
    logger.info("━" * 60)
    if config.PRELOAD_MODELS:
        logger.info("  Loading models — /health returns 503 until ready")
    else:
        logger.info("  Model preloading disabled for API; worker owns transcription models")
    logger.info("━" * 60)

    if config.PRELOAD_MODELS:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, preload_all_models)
            _models_ready = True
        except Exception as exc:
            _startup_error = str(exc)
            logger.error(f"  ❌ Model loading FAILED: {exc}")
            yield
            return
    else:
        _models_ready = True

    logger.info("━" * 60)
    logger.info(f"  ✅ API ready      — http://{config.HOST}:{config.API_PORT}")
    logger.info(f"  📖 Swagger UI     — http://localhost:{config.API_PORT}/docs")
    logger.info(f"  📦 Max upload     — {config.MAX_UPLOAD_MB} MB")
    logger.info(f"  🔑 Auth           — x-api-key header required")
    logger.info("━" * 60)

    yield

    logger.info("━" * 60)
    logger.info("  API shutting down. Goodbye.")
    logger.info("━" * 60)


# ════════════════════════════════════════════════
# App
# ════════════════════════════════════════════════

app = FastAPI(
    title="Hindi Speech-to-Text API",
    description="Transcribe Hindi audio/video files and live audio streams",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════
# Request logging middleware
# ════════════════════════════════════════════════

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    status = response.status_code

    if status < 300:
        label = f"✅ {status}"
    elif status < 400:
        label = f"↪️  {status}"
    elif status < 500:
        label = f"⚠️  {status}"
    else:
        label = f"❌ {status}"

    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        f"{request.method:<7} {request.url.path:<22} "
        f"{label}  {duration_ms:>7.1f} ms  [{client_ip}]"
    )
    return response


# ════════════════════════════════════════════════
# Public endpoints
# ════════════════════════════════════════════════

@app.get("/", tags=["General"])
async def root():
    return {
        "service": "Hindi Speech-to-Text API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "auth": "All endpoints require header: x-api-key: <your_key>",
    }


@app.get("/realtime", include_in_schema=False)
async def realtime_page():
    realtime_html = Path(__file__).resolve().parent.parent / "static" / "realtime.html"
    return FileResponse(realtime_html)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/health", tags=["General"])
async def health():
    if _startup_error:
        return Response(
            content=f'{{"status":"error","detail":"{_startup_error}"}}',
            status_code=503,
            media_type="application/json",
        )
    if not _models_ready:
        return Response(
            content='{"status":"starting","detail":"Models are loading, please wait."}',
            status_code=503,
            media_type="application/json",
        )
    return {"status": "ok"}


app.include_router(router)
