"""
transcribe.py – The transcription engine.

Pipeline:
  Audio → Vosk (speech-to-text) → Cadence-Fast (punctuation) → final text
"""

import asyncio
import json
import logging
import queue
import threading
import wave
from typing import Callable

import numpy as np
from vosk import KaldiRecognizer, Model, SetLogLevel

import src.config as config
from src.utils import Segment, hindi_post_process

SetLogLevel(-1)

logger = logging.getLogger("hindi_stt")
# ... rest of the file

# ════════════════════════════════════════════════
# Concurrency semaphore
# ════════════════════════════════════════════════

_transcription_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _transcription_semaphore
    if _transcription_semaphore is None:
        _transcription_semaphore = asyncio.Semaphore(
            config.MAX_CONCURRENT_TRANSCRIPTIONS
        )
    return _transcription_semaphore


# ════════════════════════════════════════════════
# Model singletons
# ════════════════════════════════════════════════

_vosk_model: Model | None = None
_punct_model = None


def get_vosk_model() -> Model:
    global _vosk_model
    if _vosk_model is None:
        logger.info(f"[VOSK] Loading model from {config.VOSK_MODEL_PATH}…")
        _vosk_model = Model(config.VOSK_MODEL_PATH)
        logger.info("[VOSK] Acoustic model ready.")
    return _vosk_model


def get_punct_model():
    """Load Cadence-Fast (cached after first call). Fully offline."""
    global _punct_model
    if _punct_model is None:
        logger.info("[PUNCT] Loading Cadence-Fast punctuation model…")
        from cadence import PunctuationModel
        model_path = config.PUNCT_MODEL_PATH if config.PUNCT_MODEL_PATH else None
        _punct_model = PunctuationModel(
            model="Cadence-Fast",
            model_path=model_path,
            cpu=True,
            verbose=False,
        )
        logger.info("[PUNCT] Cadence-Fast ready.")
    return _punct_model


# ════════════════════════════════════════════════
# Startup warmup
# ════════════════════════════════════════════════

def preload_all_models() -> None:
    """Load and warm up all models. Called once from the lifespan thread."""
    logger.info("[STARTUP] Pre-loading all models…")

    model = get_vosk_model()
    punct = get_punct_model()

    logger.info("[STARTUP] Warming up Vosk…")
    silence = np.zeros(int(config.SAMPLE_RATE * 0.5), dtype=np.int16).tobytes()
    warmup_rec = KaldiRecognizer(model, config.SAMPLE_RATE)
    warmup_rec.SetWords(True)
    warmup_rec.AcceptWaveform(silence)
    warmup_rec.FinalResult()
    del warmup_rec

    logger.info("[STARTUP] Warming up Cadence-Fast…")
    try:
        punct.punctuate(["नमस्ते यह एक परीक्षण है", "क्या आप ठीक हैं"])
    except Exception as e:
        logger.warning(f"[STARTUP] Warmup warning: {e}")

    logger.info("[STARTUP] All models loaded and ready.")


# ════════════════════════════════════════════════
# Punctuation — batch (file mode)
# ════════════════════════════════════════════════

def punctuate_batch(texts: list[str]) -> list[str]:
    """Punctuate a list of raw Vosk texts in one Cadence batch call."""
    if not texts:
        return texts
    try:
        results = get_punct_model().punctuate(texts)
        return [hindi_post_process(r) for r in results]
    except Exception as e:
        logger.warning(f"[PIPELINE] Cadence error — returning unpunctuated: {e}")
        return [hindi_post_process(t) for t in texts]


def punctuate_streaming_final(text: str) -> str:
    """Punctuate a single Vosk final. Runs inside CadenceWorker thread."""
    if not text or not text.strip():
        return text
    try:
        results = get_punct_model().punctuate([text.strip()])
        return hindi_post_process(results[0] if results else text)
    except Exception as e:
        logger.warning(f"[STREAM] Cadence error — returning unpunctuated: {e}")
        return hindi_post_process(text)


# ════════════════════════════════════════════════
# CadenceWorker — off-hot-path punctuation
# ════════════════════════════════════════════════

_WORKER_STOP = object()


class CadenceWorker:
    """Background thread for off-hot-path Cadence punctuation."""

    def __init__(self, on_result: Callable[[str], None]) -> None:
        self._q: "queue.Queue[str | object]" = queue.Queue()
        self._on_result = on_result
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "CadenceWorker":
        self._thread.start()
        return self

    def submit(self, text: str) -> None:
        """Queue a raw Vosk final for punctuation. Returns immediately."""
        if text and text.strip():
            self._q.put(text)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait for the in-flight item to finish."""
        self._q.put(_WORKER_STOP)
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _WORKER_STOP:
                break
            try:
                self._on_result(punctuate_streaming_final(item))  # type: ignore[arg-type]
            except Exception as e:
                logger.error(f"[CADENCE WORKER] Unexpected error: {e}")
                self._on_result(hindi_post_process(item))  # type: ignore[arg-type]


# ════════════════════════════════════════════════
# File transcription — sync core
# ════════════════════════════════════════════════

def transcribe_wav(wav_path: str) -> list[Segment]:
    """
    Transcribe a 16 kHz mono WAV file (synchronous, CPU-bound).
    """
    model = get_vosk_model()
    raw_segments: list[Segment] = []

    with wave.open(wav_path, "rb") as wf:
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)

        while True:
            data = wf.readframes(config.CHUNK_SIZE)
            if not data:
                break
            if rec.AcceptWaveform(data):
                seg = _parse_result(json.loads(rec.Result()))
                if seg:
                    raw_segments.append(seg)

        seg = _parse_result(json.loads(rec.FinalResult()))
        if seg:
            raw_segments.append(seg)

    if not raw_segments:
        return raw_segments

    raw_texts = [s.text for s in raw_segments]
    punctuated = punctuate_batch(raw_texts)
    for seg, ptext in zip(raw_segments, punctuated):
        seg.text = ptext

    return raw_segments


async def transcribe_wav_async(wav_path: str) -> list[Segment]:
    """
    Non-blocking wrapper around transcribe_wav for use in async handlers.
    """
    sem = _get_semaphore()
    loop = asyncio.get_running_loop()

    async with sem:
        logger.info(f"[TRANSCRIBE] Starting transcription for {wav_path}")
        return await loop.run_in_executor(None, transcribe_wav, wav_path)


# ════════════════════════════════════════════════
# Segment parser
# ════════════════════════════════════════════════

def _parse_result(result: dict) -> Segment | None:
    text = result.get("text", "").strip()
    if not text:
        return None

    words = result.get("result", [])
    if words:
        start = words[0].get("start", 0.0)
        end = words[-1].get("end", 0.0)
        confs = [w.get("conf", 0.0) for w in words]
        confidence = sum(confs) / len(confs) if confs else 0.0
    else:
        start, end, confidence = 0.0, 0.0, 0.0

    return Segment(
        start=round(start, 3),
        end=round(end, 3),
        text=text,
        confidence=round(confidence, 4),
    )


# ════════════════════════════════════════════════
# Streaming — real-time mic / WebSocket
# ════════════════════════════════════════════════

STREAM_CHUNK_FRAMES = 1600


def create_recognizer() -> KaldiRecognizer:
    """Create a fresh Vosk recognizer for a new streaming session."""
    rec = KaldiRecognizer(get_vosk_model(), config.SAMPLE_RATE)
    rec.SetWords(True)
    return rec


def process_streaming_chunk(rec: KaldiRecognizer, pcm_bytes: bytes) -> dict:
    """
    Feed one PCM chunk to Vosk and return what it has right now.
    """
    if rec.AcceptWaveform(pcm_bytes):
        text = json.loads(rec.Result()).get("text", "").strip()
        return {"type": "final", "text": text} if text else {"type": "empty"}
    else:
        text = json.loads(rec.PartialResult()).get("partial", "").strip()
        return {"type": "partial", "text": text} if text else {"type": "empty"}


def finalize_stream(rec: KaldiRecognizer) -> dict:
    """Flush any remaining audio from Vosk's buffer when the stream ends."""
    text = json.loads(rec.FinalResult()).get("text", "").strip()
    return {"type": "final", "text": text} if text else {"type": "empty"}