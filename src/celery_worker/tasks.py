"""
tasks.py – Celery application and transcription task.
"""

import logging
from pathlib import Path

from celery import Celery
from celery.signals import worker_process_init

# Import celeryconfig from the same directory
from . import celeryconfig

logger = logging.getLogger("hindi_stt")

# Celery application
celery_app = Celery("hindi_stt")
celery_app.config_from_object(celeryconfig)


@celery_app.task(
    bind=True,
    name="src.celery_worker.tasks.transcribe_file_task",
    max_retries=2,
    default_retry_delay=5,
    acks_late=True,
    reject_on_worker_lost=True,
    track_started=True,
)
def transcribe_file_task(self, wav_path: str, original_filename: str) -> dict:
    """Transcribe a WAV file and return a result dict."""
    logger.info(f"[TASK] ▶ Starting  : {original_filename}  (job={self.request.id})")
    logger.info(f"[TASK]   WAV path  : {wav_path}")

    self.update_state(state="STARTED", meta={"filename": original_filename})

    wav_path_obj = Path(wav_path)

    if not wav_path_obj.exists():
        raise RuntimeError(
            f"WAV file not found: {wav_path}. "
            "Ensure the API server and Celery worker share the same filesystem / volume."
        )

    try:
        from src.transcribe import transcribe_wav
        from src.utils import get_duration

        segments = transcribe_wav(wav_path)
        duration = get_duration(wav_path)
        full_text = " ".join(s.text for s in segments)

        logger.info(
            f"[TASK] ✅ Done      : {original_filename} | "
            f"{duration:.1f}s | {len(segments)} segments"
        )

        wav_path_obj.unlink(missing_ok=True)
        logger.debug(f"[TASK] 🗑 Cleaned up temp WAV: {wav_path}")

        return {
            "status": "done",
            "filename": original_filename,
            "duration_seconds": round(duration, 2),
            "num_segments": len(segments),
            "full_text": full_text,
            "segments": [
                {
                    "start": round(s.start, 3),
                    "end": round(s.end, 3),
                    "text": s.text,
                    "confidence": round(s.confidence, 4),
                }
                for s in segments
            ],
        }

    except RuntimeError as exc:
        wav_path_obj.unlink(missing_ok=True)
        logger.error(f"[TASK] ❌ Non-retryable failure: {original_filename} — {exc}")
        raise

    except Exception as exc:
        logger.error(f"[TASK] ⚠️ Unexpected error (will retry): {original_filename} — {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            wav_path_obj.unlink(missing_ok=True)
            logger.error(f"[TASK] ❌ All retries exhausted for {original_filename}")
            raise