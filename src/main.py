"""
main.py – Local CLI for testing the transcription engine.

Usage:
    python -m src.main file <audio_file>    # transcribe a file
    python -m src.main mic                   # live microphone
"""

import queue
import sys
import threading
import time
from pathlib import Path

import src.config as config
from src.transcribe import (
    CadenceWorker,
    create_recognizer,
    finalize_stream,
    preload_all_models,
    process_streaming_chunk,
    transcribe_wav,
)
from src.utils import convert_to_wav, get_duration, validate_file
# ... rest of the file

# ════════════════════════════════════════════════
# file sub-command
# ════════════════════════════════════════════════

def cmd_file(audio_path: str) -> int:
    if not Path(audio_path).exists():
        print(f"Error: file not found: {audio_path}", file=sys.stderr)
        return 1

    err = validate_file(audio_path)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    print("Loading models…", file=sys.stderr)
    preload_all_models()

    print("Converting to 16 kHz mono WAV…", file=sys.stderr)
    wav_path = convert_to_wav(audio_path)

    try:
        duration = get_duration(wav_path)
        print(f"Transcribing {duration:.1f} s of audio…", file=sys.stderr)
        print("", file=sys.stderr)

        segments = transcribe_wav(wav_path)
        print(" ".join(seg.text for seg in segments))

        print("", file=sys.stderr)
        print(f"Done. {len(segments)} segment(s).", file=sys.stderr)
        return 0
    finally:
        Path(wav_path).unlink(missing_ok=True)


# ════════════════════════════════════════════════
# mic sub-command
# ════════════════════════════════════════════════

def cmd_mic() -> int:
    try:
        import sounddevice as sd
    except ImportError:
        print(
            "Error: sounddevice is not installed.\n"
            "       Run: pip install sounddevice",
            file=sys.stderr,
        )
        return 1

    print("Loading models…", file=sys.stderr)
    preload_all_models()

    MIC_CHUNK = 480
    FLUSH_AFTER = 0.5

    rec = create_recognizer()
    audio_q: queue.Queue = queue.Queue()

    buffer_lock = threading.Lock()
    sentence_buffer: list[str] = []
    last_final_time: list[float] = [0.0]
    stop_event = threading.Event()

    def on_cadence_result(text: str) -> None:
        sys.stdout.write(text + " ")
        sys.stdout.flush()

    worker = CadenceWorker(on_result=on_cadence_result).start()

    def flush_buffer() -> None:
        with buffer_lock:
            if not sentence_buffer:
                return
            chunk = " ".join(sentence_buffer)
            sentence_buffer.clear()
        worker.submit(chunk)

    def silence_flusher() -> None:
        while not stop_event.is_set():
            time.sleep(0.05)
            with buffer_lock:
                has_text = bool(sentence_buffer)
                elapsed = time.time() - last_final_time[0]
            if has_text and elapsed > FLUSH_AFTER:
                flush_buffer()

    threading.Thread(target=silence_flusher, daemon=True).start()

    def add_final(text: str) -> None:
        with buffer_lock:
            sentence_buffer.append(text)
            last_final_time[0] = time.time()

    def audio_callback(indata, frames, time_info, status) -> None:
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        audio_q.put(bytes(indata))

    print("", file=sys.stderr)
    print("🎙️  Listening. Speak in Hindi. Press Ctrl+C to stop.", file=sys.stderr)
    print("", file=sys.stderr)

    try:
        with sd.RawInputStream(
            samplerate=config.SAMPLE_RATE,
            blocksize=MIC_CHUNK,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            while True:
                data = audio_q.get()
                result = process_streaming_chunk(rec, data)
                if result["type"] == "final" and result["text"].strip():
                    add_final(result["text"])

    except KeyboardInterrupt:
        stop_event.set()
        final = finalize_stream(rec)
        if final["type"] == "final" and final["text"].strip():
            add_final(final["text"])
        flush_buffer()
        worker.stop(timeout=5.0)
        sys.stdout.write("\n")
        sys.stdout.flush()
        print("Stopped.", file=sys.stderr)
        return 0


# ════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1

    cmd = sys.argv[1]

    if cmd == "file":
        if len(sys.argv) < 3:
            print("Error: missing audio file path.", file=sys.stderr)
            return 1
        return cmd_file(sys.argv[2])

    if cmd == "mic":
        return cmd_mic()

    print(f"Error: unknown command '{cmd}'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())