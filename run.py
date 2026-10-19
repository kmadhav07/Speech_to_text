#!/usr/bin/env python3
"""
Root entry point for Hindi Transcription System.

Usage:
    python run.py api      # Start FastAPI server
    python run.py worker   # Start Celery worker
    python run.py file <audio_file>  # Transcribe a file (CLI)
    python run.py mic      # Live microphone transcription (CLI)
"""

import sys
import subprocess
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    command = sys.argv[1]

    try:
        if command == "api":
            print("Starting FastAPI server...")
            subprocess.run([
                "uvicorn", "src.api:app",
                "--host", "0.0.0.0",
                "--port", "8010"
            ])
            return 0

        elif command == "worker":
            print("Starting Celery worker...")
            subprocess.run([
                "python", "-m", "src.celery_worker.worker"
            ] + sys.argv[2:])
            return 0

        elif command in ("file", "mic"):
            print(f"Running CLI command: {command}")
            subprocess.run([
                "python", "-m", "src.main"
            ] + sys.argv[1:])
            return 0

        elif command == "cli":
            if len(sys.argv) < 3:
                print("Usage: python run.py cli [file <path> | mic]")
                return 1
            print(f"Running CLI command: {sys.argv[2]}")
            subprocess.run([
                "python", "-m", "src.main"
            ] + sys.argv[2:])
            return 0

        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            return 1

    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
