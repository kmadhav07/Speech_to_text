"""
worker.py – Celery worker entrypoint.

Usage (run from HINDI_TRANSCRIPTION/ directory):
    python -m src.celery_worker.worker
    python -m src.celery_worker.worker --workers 2
"""

import argparse
import multiprocessing
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def calculate_worker_count() -> int:
    cpu_count = multiprocessing.cpu_count()
    workers = max(1, cpu_count - 1)
    workers = min(workers, 8)
    return workers


def main():
    parser = argparse.ArgumentParser(description="Start Hindi STT Celery workers")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes")
    parser.add_argument("--loglevel", default="info", choices=["debug", "info", "warning", "error"])
    parser.add_argument("--queues", default="transcription", help="Comma-separated queues")
    args = parser.parse_args()

    worker_count = args.workers or calculate_worker_count()
    cpu_count = multiprocessing.cpu_count()

    estimated_ram_gb = worker_count * 1.5

    print("━" * 60)
    print("  Hindi STT — Celery Worker Launcher")
    print("━" * 60)
    print(f"  CPU cores available  : {cpu_count}")
    print(f"  Workers to start     : {worker_count}")
    print(f"  Queue(s)             : {args.queues}")
    print(f"  Log level            : {args.loglevel}")
    print(f"  ⚠️  Estimated RAM   : ~{estimated_ram_gb:.0f} GB")
    print("━" * 60)
    print()

    from src.celery_worker.tasks import celery_app

    worker_argv = [
        "worker",
        f"--concurrency={worker_count}",
        "--pool=prefork",
        f"--loglevel={args.loglevel}",
        f"--queues={args.queues}",
        "--without-gossip",
        "--without-mingle",
        "--hostname=worker@%h",
    ]

    print(f"  Running: celery {' '.join(worker_argv)}")
    print()

    celery_app.worker_main(argv=worker_argv)


if __name__ == "__main__":
    main()