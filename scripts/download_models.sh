#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
MODELS_DIR="$BASE_DIR/models"
VOSK_DIR="$MODELS_DIR/vosk"

echo "============================================================"
echo "  Downloading Hindi STT Models"
echo "============================================================"

mkdir -p "$MODELS_DIR"

if [ -d "$VOSK_DIR" ] && [ "$(ls -A "$VOSK_DIR")" ]; then
    echo "✅ Vosk model already exists at $VOSK_DIR"
else
    echo "📥 Downloading Vosk Hindi model..."
    curl -L "https://alphacephei.com/vosk/models/vosk-model-hi-0.22.zip" -o "$MODELS_DIR/vosk-model-hi-0.22.zip"
    echo "📦 Extracting..."
    unzip -q "$MODELS_DIR/vosk-model-hi-0.22.zip" -d "$MODELS_DIR"
    mv "$MODELS_DIR/vosk-model-hi-0.22" "$VOSK_DIR"
    rm -f "$MODELS_DIR/vosk-model-hi-0.22.zip"
    echo "✅ Vosk model installed at $VOSK_DIR"
fi

echo "============================================================"
echo "  Models ready."
echo "============================================================"
