"""
utils.py – Helper functions and data structures.
"""

import asyncio
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import src.config as config
# ... rest of the file
# ════════════════════════════════════════════════
# Segment
# ════════════════════════════════════════════════

@dataclass
class Segment:
    start: float
    end: float
    text: str
    confidence: float = 0.0


# ════════════════════════════════════════════════
# Hindi post-processing
# ════════════════════════════════════════════════

def _has_devanagari(text: str) -> bool:
    return any("\u0900" <= c <= "\u097F" for c in text)


def hindi_post_process(text: str) -> str:
    """Convert Cadence output to proper Hindi punctuation."""
    if not text or not text.strip():
        return text

    text = text.strip()
    if not _has_devanagari(text):
        return text

    # English period → purna viram (digit guard keeps 3.14 intact)
    text = re.sub(r"(?<!\d)\.(?!\d)", "।", text)

    # Fix spacing around punctuation
    text = re.sub(r"\s+([।?,!;:.])", r"\1", text)
    text = re.sub(r"([।?,!;:.])([^\s।?,!;:.\d])", r"\1 \2", text)

    # Collapse repeated punctuation
    text = re.sub(r"[।]{2,}", "।", text)
    text = re.sub(r"[?]{2,}", "?", text)
    text = re.sub(r"[,]{2,}", ",", text)

    # Trailing comma → purna viram
    if text.endswith(","):
        text = text[:-1] + "।"

    return text.strip()


# ════════════════════════════════════════════════
# File validation
# ════════════════════════════════════════════════

def validate_file(filename: str) -> str | None:
    """Return None if the extension is allowed, else return an error string."""
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        return (
            f"'.{ext}' is not supported. "
            f"Allowed formats: {', '.join(sorted(config.ALLOWED_EXTENSIONS))}"
        )
    return None


# ════════════════════════════════════════════════
# FFmpeg wrapper
# ════════════════════════════════════════════════

def convert_to_wav(input_path: str, output_dir: str | None = None) -> str:
    """Convert any audio/video file to 16 kHz mono PCM WAV (synchronous)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=output_dir) as f:
        output_path = f.name

    _run_ffmpeg(input_path, output_path)
    return output_path


async def convert_to_wav_async(input_path: str, output_dir: str | None = None) -> str:
    """Non-blocking version of convert_to_wav for use inside async handlers."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=output_dir) as f:
        output_path = f.name

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_ffmpeg, input_path, output_path)
    return output_path


def _run_ffmpeg(input_path: str, output_path: str) -> None:
    """Internal: run FFmpeg synchronously. Raises RuntimeError on failure."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ar", str(config.SAMPLE_RATE),
        "-ac", "1",
        "-sample_fmt", "s16",
        "-f", "wav",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        Path(output_path).unlink(missing_ok=True)
        raise RuntimeError(
            f"FFmpeg conversion failed:\n{result.stderr.decode(errors='replace')}"
        )


# ════════════════════════════════════════════════
# WAV helpers
# ════════════════════════════════════════════════

def get_duration(wav_path: str) -> float:
    """Return duration of a WAV file in seconds."""
    with wave.open(wav_path, "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


# ════════════════════════════════════════════════
# SRT subtitle export
# ════════════════════════════════════════════════

def segments_to_srt(segments: list[Segment]) -> str:
    """Convert a list of Segments into SRT subtitle format."""
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def _srt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"