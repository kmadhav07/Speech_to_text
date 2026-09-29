"""
endpoints.py – All API endpoints live here.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from celery.result import AsyncResult
from fastapi import (
    APIRouter, File, Header, HTTPException,
    Request, UploadFile, WebSocket, WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import src.config as config
from src.transcribe import (
    CadenceWorker,
    create_recognizer,
    finalize_stream,
    process_streaming_chunk,
    transcribe_wav_async,
)
from src.utils import convert_to_wav_async, get_duration, validate_file

# Celery tasks for async background queue
from src.celery_worker.tasks import celery_app, transcribe_file_task

logger = logging.getLogger("hindi_stt")
router = APIRouter()

_UPLOAD_CHUNK = 1024 * 1024


def verify_api_key(x_api_key: str) -> None:
    if x_api_key != config.API_KEY:
        logger.warning("Unauthorized request — invalid API key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class JobAccepted(BaseModel):
    job_id: str
    status: str = "pending"
    poll_url: str


class SegmentOut(BaseModel):
    start: float
    end: float
    text: str
    confidence: float


class TranscriptionOut(BaseModel):
    filename: str
    duration_seconds: float
    num_segments: int
    full_text: str
    segments: list[SegmentOut]


class JobStatusOut(BaseModel):
    job_id: str
    status: str
    result: TranscriptionOut | None = None
    error: str | None = None


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe_endpoint(
    request: Request,
    file: UploadFile = File(...),
    x_api_key: str = Header(...),
):
    """
    Transcribe Hindi audio/video file and return the transcription result directly in the HTTP response.
    """
    verify_api_key(x_api_key)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    err = validate_file(file.filename)
    if err:
        raise HTTPException(status_code=415, detail=err)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Max {config.MAX_UPLOAD_MB} MB.")

    logger.info(f"[TRANSCRIBE] Receiving: {file.filename}")

    tmp_path = None
    wav_path = None

    try:
        suffix = Path(file.filename).suffix

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            received_bytes = 0

            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                received_bytes += len(chunk)
                if received_bytes > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large. Max {config.MAX_UPLOAD_MB} MB.")
                tmp.write(chunk)

        wav_path = await convert_to_wav_async(tmp_path, output_dir=config.DATA_DIR)
        task = transcribe_file_task.delay(wav_path, file.filename)
        wav_path = None  # Celery task cleans up wav_path on completion

        # Wait for Celery worker to complete and return the result directly
        loop = asyncio.get_running_loop()
        task_result = await loop.run_in_executor(None, task.get, 300)

        return TranscriptionOut(
            filename=task_result["filename"],
            duration_seconds=task_result["duration_seconds"],
            num_segments=task_result["num_segments"],
            full_text=task_result["full_text"],
            segments=[SegmentOut(**s) for s in task_result["segments"]],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TRANSCRIBE] Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        if wav_path:
            Path(wav_path).unlink(missing_ok=True)


@router.post("/transcribe-async", response_model=JobAccepted, status_code=202)
async def transcribe_async_endpoint(
    request: Request,
    file: UploadFile = File(...),
    x_api_key: str = Header(...),
):
    """
    Queue large audio/video files for background processing via Celery.
    Returns a job_id immediately to poll via GET /job/{job_id}.
    """
    verify_api_key(x_api_key)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    err = validate_file(file.filename)
    if err:
        raise HTTPException(status_code=415, detail=err)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Max {config.MAX_UPLOAD_MB} MB.")

    logger.info(f"[TRANSCRIBE-ASYNC] Receiving: {file.filename}")

    tmp_path = None
    wav_path = None

    try:
        suffix = Path(file.filename).suffix

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            received_bytes = 0

            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                received_bytes += len(chunk)
                if received_bytes > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large. Max {config.MAX_UPLOAD_MB} MB.")
                tmp.write(chunk)

        # Store queued-job audio in the shared volume so the worker can read it.
        wav_path = await convert_to_wav_async(tmp_path, output_dir=config.DATA_DIR)

        task = transcribe_file_task.delay(wav_path, file.filename)
        wav_path = None

        return JobAccepted(job_id=task.id, status="pending", poll_url=f"/job/{task.id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TRANSCRIBE-ASYNC] Failed to queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue transcription: {e}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        if wav_path:
            Path(wav_path).unlink(missing_ok=True)


@router.get("/job/{job_id}", response_model=JobStatusOut)
async def get_job_status(job_id: str, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)

    result: AsyncResult = celery_app.AsyncResult(job_id)
    state = result.state
    logger.debug(f"[JOB] Polling job_id={job_id} state={state}")

    if state == "PENDING":
        return JobStatusOut(job_id=job_id, status="pending")
    elif state in ("STARTED", "RETRY"):
        return JobStatusOut(job_id=job_id, status="processing")
    elif state == "SUCCESS":
        data = result.result
        return JobStatusOut(
            job_id=job_id,
            status="done",
            result=TranscriptionOut(
                filename=data["filename"],
                duration_seconds=data["duration_seconds"],
                num_segments=data["num_segments"],
                full_text=data["full_text"],
                segments=[SegmentOut(**s) for s in data["segments"]],
            ),
        )
    elif state in ("FAILURE", "REVOKED"):
        error_msg = str(result.result) if result.result else "Unknown error"
        return JSONResponse(status_code=500, content={"job_id": job_id, "status": "failed", "error": error_msg})
    else:
        return JobStatusOut(job_id=job_id, status="pending")


@router.websocket("/stream")
async def stream_endpoint(websocket: WebSocket, api_key: str = ""):
    provided_key = api_key or websocket.query_params.get("api_key", "")
    if provided_key != config.API_KEY and provided_key.replace(" ", "+") == config.API_KEY:
        provided_key = config.API_KEY

    if provided_key != config.API_KEY:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    rec = await loop.run_in_executor(None, create_recognizer)
    client = f"{websocket.client.host}:{websocket.client.port}"

    await websocket.send_json({"type": "ready", "sample_rate": config.SAMPLE_RATE})

    def on_punctuated(text: str) -> None:
        async def _send():
            try:
                await websocket.send_json({"type": "final", "text": text})
            except Exception:
                pass
        loop.call_soon_threadsafe(asyncio.ensure_future, _send())

    worker = CadenceWorker(on_result=on_punctuated).start()

    try:
        while True:
            data = await websocket.receive_bytes()
            if not data:
                continue
            result = process_streaming_chunk(rec, data)
            if result["type"] == "partial":
                await websocket.send_json(result)
            elif result["type"] == "final" and result["text"]:
                worker.submit(result["text"])
    except WebSocketDisconnect:
        final = finalize_stream(rec)
        if final["type"] == "final" and final["text"]:
            worker.submit(final["text"])
        worker.stop(timeout=5.0)
    except Exception as e:
        logger.error(f"[WS] Error: {e}", exc_info=True)
        worker.stop(timeout=1.0)