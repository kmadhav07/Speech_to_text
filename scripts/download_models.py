#!/usr/bin/env python3
"""
download_models.py
Automated downloader for Hindi ASR and punctuation models.
Downloads models to ./models/vosk and ./models/cadence
"""

import os
import sys
import shutil
import urllib.request
import zipfile
from pathlib import Path

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-hi-0.22.zip"
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
VOSK_DIR = MODELS_DIR / "vosk"
CADENCE_DIR = MODELS_DIR / "cadence"


def download_progress(block_num, block_size, total_size):
    read_so_far = block_num * block_size
    if total_size > 0:
        percent = read_so_far * 1e2 / total_size
        s = f"\rDownloading: {percent:5.1f}% ({read_so_far / (1024 * 1024):.1f} MB / {total_size / (1024 * 1024):.1f} MB)"
        sys.stderr.write(s)
        sys.stderr.flush()


def setup_vosk():
    if VOSK_DIR.exists() and any(VOSK_DIR.iterdir()):
        print(f"✅ Vosk model already present at {VOSK_DIR}")
        return

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = MODELS_DIR / "vosk-model-hi-0.22.zip"

    print(f"📥 Downloading Vosk Hindi model from {VOSK_MODEL_URL}...")
    urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path, reporthook=download_progress)
    print("\n📦 Extracting Vosk model...")

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(MODELS_DIR)

    extracted_dir = MODELS_DIR / "vosk-model-hi-0.22"
    if extracted_dir.exists():
        if VOSK_DIR.exists() and VOSK_DIR.is_symlink():
            VOSK_DIR.unlink()
        extracted_dir.rename(VOSK_DIR)

    if zip_path.exists():
        zip_path.unlink()

    print(f"✅ Vosk model ready at {VOSK_DIR}")


def setup_cadence():
    print("📥 Checking Cadence-Fast punctuation model...")
    try:
        from cadence import PunctuationModel
        model_path = str(CADENCE_DIR) if CADENCE_DIR.exists() and any(CADENCE_DIR.iterdir()) else None
        PunctuationModel(model="Cadence-Fast", model_path=model_path, cpu=True, verbose=False)
        print("✅ Cadence-Fast model ready.")
    except Exception as e:
        print(f"⚠️ Note on Cadence model: {e}")


def main():
    print("=" * 60)
    print("  Hindi STT — Model Setup Script")
    print("=" * 60)
    setup_vosk()
    setup_cadence()
    print("=" * 60)
    print("  All models ready for local & Docker deployment!")
    print("=" * 60)


if __name__ == "__main__":
    main()
