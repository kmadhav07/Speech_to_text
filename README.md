# Hindi Speech-to-Text API

> A complete Hindi speech transcription system.
> Converts any Hindi audio or video file into accurate punctuated text and streams live microphone input — entirely offline, running on CPU (tested on Apple Silicon & Linux).

**Tech stack:** Vosk (ASR) + Cadence-Fast (punctuation) + FastAPI + Celery + Redis + Docker + FFmpeg

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Why These Technologies](#why-these-technologies)
3. [Project Structure](#project-structure)
4. [Prerequisites](#prerequisites)
5. [Quick Start with Docker](#quick-start-with-docker)
6. [Local Installation (Without Docker)](#local-installation-without-docker)
7. [Configuration (.env)](#configuration-env)
8. [Running the System](#running-the-system)
9. [API Endpoints](#api-endpoints)
10. [How Each File Works](#how-each-file-works)
11. [Celery + Redis Worker Queue](#celery--redis-worker-queue)
12. [Real-time Mic Streaming](#real-time-mic-streaming)
13. [Model Details](#model-details)
14. [DevOps & Production Deployment Guide](#devops--production-deployment-guide)
15. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                 CLIENT                                  │
│         Browser (/realtime) / Swagger (/docs) / curl / Python CLI       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ HTTP / WebSocket
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (src/api.py)                      │
│                                                                         │
│   POST /transcribe       ──►  direct sync transcription (instant JSON)  │
│   POST /transcribe-async ──►  queues Celery task (returns job_id 202)   │
│   GET /job/{id}          ──►  polls task state & result from Redis DB 1 │
│   WS /stream             ──►  real-time PCM chunks ──► CadenceWorker    │
│   GET /realtime          ──►  serves static/realtime.html browser UI    │
│   GET /health            ──►  service health check (200 OK)             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Task dispatched via Redis DB 0
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Redis (message broker + result store)               │
│   DB 0 — task queue (broker)                                            │
│   DB 1 — task results (backend)                                         │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ Worker picks task
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Celery Workers (src/celery/worker.py)               │
│                                                                         │
│   Worker 1: WAV ──► Vosk (ASR) ──► Cadence-Fast (Punct) ──► Result      │
│   Worker N: ...                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Transcription Processing Flows:**
1. **Synchronous Flow (`POST /transcribe`):** Client sends audio $\rightarrow$ Server converts to WAV via FFmpeg $\rightarrow$ Transcribes and adds Hindi punctuation $\rightarrow$ Returns full transcription JSON payload directly in the HTTP response.
2. **Asynchronous Queue Flow (`POST /transcribe-async`):** Client sends large audio $\rightarrow$ Server queues Celery task in Redis DB 0 and returns `job_id` in **< 100ms** (HTTP 202) $\rightarrow$ Worker transcribes $\rightarrow$ Result is stored in Redis DB 1 $\rightarrow$ Client polls `GET /job/{job_id}` until `status: "done"`.
3. **Live Streaming Flow (`WS /stream`):** Browser/client streams 16kHz PCM audio $\rightarrow$ Vosk emits partial words live $\rightarrow$ Background `CadenceWorker` adds punctuation on silence and streams formatted text back.

---

## Why These Technologies

### Vosk — Offline Hindi ASR
Vosk was chosen after evaluating multiple ASR models against hard constraints (no GPU required, no auth, $\le$ 5 GB footprint, fully offline):
- **High accuracy:** Excellent transcription on real Hindi speech and interview audio.
- **Native real-time streaming:** Supports chunk-by-chunk streaming via `KaldiRecognizer.AcceptWaveform()`.
- **Low RAM footprint:** ~200MB memory footprint per instance, leaving CPU and RAM headroom for language models.
- **Offline & Open Source:** Apache 2.0 license, runs completely locally without external API calls.

### Cadence-Fast — Hindi Punctuation
Vosk outputs raw unpunctuated text. Cadence-Fast (gemma-3-270M fine-tuned by AI4Bharat) understands sentence context to add commas, question marks, and Hindi purna viram (`।`). MIT license, fully offline.

### Celery + Redis — High-Concurrency Async Queue
Transcription of large files can take time. Celery and Redis decouple incoming traffic from processing:
- The API server accepts requests instantly without blocking.
- Multiple worker processes process tasks in parallel.
- Automatic retries on worker restarts with late acknowledgments (`task_acks_late=True`).

### Docker & Docker Compose — Reproducible Deployment
Containers guarantee identical environments across macOS, Linux servers, and cloud clusters without system dependency discrepancies.

---

## Project Structure

```
HINDI_TRANSCRIPTION/
├── Dockerfile                  ← Standard production Dockerfile (mounts models)
├── Dockerfile.standalone       ← Standalone Dockerfile (bakes models inside image)
├── docker-compose.yml          ← Orchestrates Redis, Web API, and Celery Worker
├── run.py                      ← Root entrypoint for running API, Worker, or CLI
├── .env                        ← Local secrets & config (never committed to Git)
├── .env.example                ← Environment template for setup & deployment
├── .gitignore                  ← Prevents committing models, venv, and secrets
├── .dockerignore               ← Keeps build context small and images secure
├── requirements.txt            ← Pinned Python dependencies
├── README.md                   ← Full system documentation
├── models/                     ← Model storage directory (gitignored)
│   ├── vosk/                   ← Vosk Hindi acoustic model weights
│   └── cadence/                ← Cadence-Fast punctuation model weights
├── scripts/
│   ├── download_models.sh      ← Automated Bash model downloader for CI/CD
│   └── download_models.py      ← Automated Python model downloader
├── static/
│   └── realtime.html           ← Browser UI for live microphone transcription
├── data/                       ← Runtime temporary audio storage (gitignored)
├── outputs/                    ← Runtime export directory (gitignored)
└── src/
    ├── api.py                  ← FastAPI application, lifespan, request logging
    ├── endpoints.py            ← API routes: /transcribe, /job/{id}, /stream, /health
    ├── transcribe.py           ← Vosk + Cadence transcription engine & worker
    ├── utils.py                ← FFmpeg conversion, validation, SRT formatter
    ├── config.py               ← Centralized configuration loaded from .env
    ├── main.py                 ← CLI tool for direct file & mic testing
    └── celery/                 ← Async task queue package
        ├── celeryconfig.py     ← Celery broker, backend, and reliability config
        ├── tasks.py            ← Celery app & transcribe_file_task definition
        └── worker.py           ← Worker launcher (auto CPU core detection)
```

---

## Prerequisites

| Requirement | Recommended Version | Purpose |
|---|---|---|
| **Docker & Docker Compose** | Recent version | Containerized runtime |
| **Python** *(if running locally)* | **3.12 exactly** | Python runtime (3.14 breaks Cadence) |
| **FFmpeg** *(if running locally)* | Any recent | Audio/video conversion to 16kHz mono WAV |
| **Redis** *(if running locally)* | 7.x | Task queue broker & result backend |

> ⚠️ **Python Version Requirement:** Python 3.12 is required for direct local execution. Newer versions (e.g. 3.14) break Cadence-Fast with `Sequential has no attribute 'weight'`.

---

## Quick Start with Docker

### Step 1 — Download Models
Run the automated downloader script to download and extract the models into `./models/`:
```bash
bash scripts/download_models.sh
```

### Step 2 — Configure Environment
Copy the environment template:
```bash
cp .env.example .env
```
Edit `.env` and set your secret API key:
```env
API_KEY=your-secure-api-key-here
```

### Step 3 — Start All Services
Start Redis, FastAPI Server, and Celery Worker in the background:
```bash
docker compose up --build -d
```

### Step 4 — Verify Running Services
```bash
# Check container status
docker compose ps

# Check API health
curl http://localhost:8000/health
# Returns: {"status": "ok"}

# View real-time logs
docker compose logs -f
```

### Step 5 — Stop Services
```bash
docker compose down
```

---

## Local Installation (Without Docker)

### Step 1 — Set up virtual environment
```bash
# Create and activate Python 3.12 virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Verify Python version
python --version   # Must show 3.12.x
```

### Step 2 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Download models
```bash
bash scripts/download_models.sh
```

### Step 4 — Start Redis
```bash
# macOS (Homebrew)
brew services start redis

# Linux (systemd)
sudo systemctl start redis

# Verify Redis is responding
redis-cli ping   # Should print: PONG
```

---

## Configuration (.env)

All settings are read from `.env`. See `.env.example` for reference:

```env
# ── Required ──────────────────────────────────────────────────────────
API_KEY=your-secure-api-key-here          # Secret key for x-api-key auth

# ── Model paths (Inside Container / Host) ─────────────────────────────
VOSK_MODEL_PATH=/models/vosk              # In-container path to Vosk model
PUNCT_MODEL_PATH=/models/cadence          # In-container path to Cadence model
VOSK_MODEL_PATH_HOST=./models/vosk        # Host path mounted by docker-compose
PUNCT_MODEL_PATH_HOST=./models/cadence    # Host path mounted by docker-compose

# ── Audio settings ────────────────────────────────────────────────────
SAMPLE_RATE=16000     # Exactly 16kHz required by Vosk
CHUNK_SIZE=4096       # Frame read chunk size

# ── File limits ───────────────────────────────────────────────────────
MAX_UPLOAD_MB=200     # Max upload size (in MB)
OUTPUT_DIR=outputs    # Directory for exports
DATA_DIR=data         # Directory for runtime audio scratch

# ── Server settings ───────────────────────────────────────────────────
HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=*        # Allowed CORS origins (* for all)
PRELOAD_MODELS=false  # Fast API startup (worker owns heavy models)

# ── Redis broker ──────────────────────────────────────────────────────
REDIS_HOST=redis      # Use 'redis' for Docker, 'localhost' for local Python
REDIS_PORT=6379
```

---

## Running the System

### Option 1: Docker (Recommended)
```bash
docker compose up -d
```

### Option 2: Local Python (3 Terminals)

#### Terminal 1 — Redis
```bash
redis-server
```

#### Terminal 2 — Celery Worker
```bash
python run.py worker --workers 1
```

#### Terminal 3 — FastAPI Web Server
```bash
python run.py api
```

### Option 3: Local CLI (No Server / Redis Needed)
```bash
# Transcribe a media file directly
python run.py file sample.mp3

# Live microphone transcription in terminal
python run.py mic
```

---

## API Endpoints

All endpoints (except `/`, `/health`, and `/realtime`) require authentication header:
`x-api-key: <your_api_key>`

---

### 1. POST /transcribe — Synchronous Transcription
Transcribes an audio/video file and returns the completed text and segments directly in the response.

```bash
curl -X POST http://localhost:8000/transcribe \
  -H "x-api-key: your-secure-api-key-here" \
  -F "file=@/path/to/audio.mp3"
```

**Response (HTTP 200 OK):**
```json
{
  "filename": "audio.mp3",
  "duration_seconds": 12.4,
  "num_segments": 2,
  "full_text": "नमस्ते यह एक परीक्षण है। आशा है कि सब ठीक है।",
  "segments": [
    {
      "start": 0.0,
      "end": 2.5,
      "text": "नमस्ते यह एक परीक्षण है।",
      "confidence": 0.94
    },
    {
      "start": 2.6,
      "end": 5.1,
      "text": "आशा है कि सब ठीक है।",
      "confidence": 0.92
    }
  ]
}
```

---

### 2. POST /transcribe-async — Background Queue Transcription
Queues long audio/video files for background processing. Returns immediately with a `job_id`.

```bash
curl -X POST http://localhost:8000/transcribe-async \
  -H "x-api-key: your-secure-api-key-here" \
  -F "file=@/path/to/long_interview.mp4"
```

**Response (HTTP 202 Accepted):**
```json
{
  "job_id": "74f1581e-475f-4c84-aeea-91fa39640729",
  "status": "pending",
  "poll_url": "/job/74f1581e-475f-4c84-aeea-91fa39640729"
}
```

---

### 3. GET /job/{job_id} — Poll Job Status
Polls the status of an asynchronous job.

```bash
curl http://localhost:8000/job/74f1581e-475f-4c84-aeea-91fa39640729 \
  -H "x-api-key: your-secure-api-key-here"
```

**Response States:**
- `pending`: Task queued in Redis, awaiting an available worker.
- `processing`: Worker is actively transcribing audio.
- `done`: Completed — `result` contains full transcription and segments.
- `failed`: Failed — `error` field explains reason.

---

### 4. WebSocket /stream — Real-time Audio Streaming
Connects via WebSocket for streaming raw 16kHz 16-bit mono PCM chunks.

- **Connection URL:** `ws://localhost:8000/stream?api_key=your-secure-api-key-here`
- **Protocol:**
  1. Server sends: `{"type": "ready", "sample_rate": 16000}`
  2. Client sends: Raw PCM binary chunks (`int16`, 16kHz, mono).
  3. Server sends: `{"type": "partial", "text": "..."}` (words in progress).
  4. Server sends: `{"type": "final", "text": "..."}` (punctuated phrase committed).

---

### 5. GET /realtime — Browser Live Microphone UI
Open **[http://localhost:8000/realtime](http://localhost:8000/realtime)** in your browser to test live speech transcription using your microphone with continuous paragraph formatting.

---

### 6. GET /health — Health Check
```bash
curl http://localhost:8000/health
```
- Returns `{"status": "ok"}` (HTTP 200) when ready.

---

### 7. GET /docs — Interactive Swagger Documentation
Open **[http://localhost:8000/docs](http://localhost:8000/docs)** to test all endpoints interactively in your browser.

---

## How Each File Works

### `src/api.py` — FastAPI Server & Middleware
- Configures FastAPI app lifespan, initializes directories, and validates `API_KEY` on startup.
- Sets up CORS middleware (`CORS_ORIGINS`).
- Implements request logging middleware that records method, path, status code, latency, and client IP.
- Serves `/realtime` UI, `/favicon.ico`, `/health`, and registers API router.

### `src/endpoints.py` — API Endpoints
- **`POST /transcribe`:** Synchronously handles file upload, converts audio to WAV via FFmpeg, executes transcription through Celery worker, and returns results.
- **`POST /transcribe-async`:** Accepts upload, queues job in Celery, returns `job_id` immediately.
- **`GET /job/{job_id}`:** Checks Celery `AsyncResult` from Redis backend and formats response.
- **`WS /stream`:** Handles live WebSocket connections, creates session recognizer, and streams output.

### `src/transcribe.py` — Transcription & Punctuation Engine
- **`get_vosk_model()` & `get_punct_model()`:** Implements thread-safe singleton pattern so models are loaded once per process and cached in memory.
- **`transcribe_wav()`:** Reads WAV in chunks, extracts word timestamps and confidence, batches text, and runs Cadence punctuation.
- **`CadenceWorker`:** Dedicated background thread that decouples real-time audio receiving from punctuation inference to avoid blocking the audio loop.
- **`hindi_post_process()`:** Replaces periods with Hindi purna viram (`।`), fixes punctuation spacing, and collapses duplicates.

### `src/utils.py` — Audio & Subtitle Utilities
- **`convert_to_wav()` & `convert_to_wav_async()`:** FFmpeg wrappers that convert any media format (`mp3`, `mp4`, `mkv`, `wav`, `m4a`, etc.) into 16 kHz mono 16-bit PCM WAV.
- **`segments_to_srt()`:** Exports timestamped transcription segments into standard SRT subtitle format.
- **`validate_file()`:** Validates file extensions against allowed formats.

### `src/config.py` — Configuration Management
- Centralized configuration module using `python-dotenv`.
- Ensures zero hardcoded credentials or paths in codebase.

### `src/celery/tasks.py` — Celery Task Definition
- Defines `transcribe_file_task` with late acknowledgments (`acks_late=True`) and retries.
- Cleans up temporary audio files safely upon task completion.

### `src/celery/worker.py` — Worker Launcher
- Auto-detects available CPU cores (`cpu_count - 1`) and launches prefork Celery worker processes.

### `src/celery/celeryconfig.py` — Celery Broker & Backend Config
- Configures Redis DB 0 as task broker and Redis DB 1 as result backend.
- Sets `worker_prefetch_multiplier=1` so tasks are evenly distributed among workers.

### `run.py` — Unified CLI Entrypoint
- Single command-line interface supporting `api`, `worker`, `file`, `mic`, and `cli` subcommands.

### `scripts/download_models.sh` & `scripts/download_models.py`
- Automation scripts that fetch the Vosk Hindi model archive from official repositories, extract it into `./models/vosk/`, and prepare Cadence models.

### `Dockerfile` vs `Dockerfile.standalone`
- **`Dockerfile`:** Standard build for local dev & VM deployments. Mounts models via volume.
- **`Dockerfile.standalone`:** Self-contained build for Kubernetes & cloud container registries (AWS ECR, Docker Hub). Automatically downloads and packages model weights inside the image.

---

## Celery + Redis Worker Queue

### Job Lifecycle
```
1. Client sends audio to POST /transcribe or POST /transcribe-async
2. Server saves file to data/ directory and creates Celery task
3. Task payload stored in Redis DB 0:
   {"wav_path": "/app/data/tmp123.wav", "original_filename": "audio.mp3"}
4. Worker process picks up task from Redis DB 0
5. Worker runs transcribe_wav() + Cadence-Fast punctuation
6. Result is saved in Redis DB 1 under key `celery-task-meta-<job_id>`
7. Temporary WAV is unlinked from storage
8. Client receives direct result (or polls GET /job/{job_id})
9. Results auto-expire from Redis after 24 hours
```

### Redis Database Separation
- **DB 0 (`redis://.../0`):** Celery task queue (broker).
- **DB 1 (`redis://.../1`):** Task results storage (backend).

### Queue Inspection & Monitoring
```bash
# Check active tasks across all workers
docker compose exec web celery -A src.celery_worker.tasks inspect active

# Check queued tasks
docker compose exec web celery -A src.celery_worker.tasks inspect reserved
```

---

## Real-time Mic Streaming

### 1. Browser Web Interface
Open **`http://localhost:8000/realtime`**, enter your API key, and click **Start microphone**.
- Speech is downsampled in the browser to 16 kHz mono.
- Streamed over WebSocket to `/stream`.
- Visual output formatted as continuous, natural paragraphs with live updates.

### 2. Terminal CLI Mode
```bash
python run.py mic
```
- Audio callback captures mic input in 30ms chunks.
- Finals accumulate in sentence buffer and are flushed to `CadenceWorker` upon silence.
- Punctuated Hindi text prints directly to standard output.

---

## Model Details

### 1. Vosk Hindi Large (`vosk-model-hi-0.22`)
- **Framework:** Kaldi ASR + TDNN (Time-Delay Neural Network).
- **Acoustic & Language Models:** Includes compiled decode graph (`graph/HCLG.fst`), vocabulary map (`graph/words.txt`), i-vector speaker extractor, and RNNLM lattice rescorer.
- **Audio Specification:** Requires 16,000 Hz, 1-channel mono, 16-bit signed PCM.

### 2. Cadence-Fast (`ai4bharat/Cadence-Fast`)
- **Architecture:** Fine-tuned Gemma-3 model trained by AI4Bharat for Indic language punctuation restoration.
- **Capabilities:** Analyzes full sentence context to accurately place commas (`,`), question marks (`?`), and Hindi purna viram (`।`).

---

## DevOps & Production Deployment Guide

### Option A: Deployment via Docker Compose (Single VM / Server)

1. **Clone repository:**
   ```bash
   git clone <repo-url>
   cd HINDI_TRANSCRIPTION
   ```
2. **Download models:**
   ```bash
   bash scripts/download_models.sh
   ```
3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Set API_KEY=<production-key>
   ```
4. **Start containers:**
   ```bash
   docker compose up --build -d
   ```
5. **Verify health:**
   ```bash
   curl http://localhost:8000/health
   # Returns: {"status": "ok"}
   ```

---

### Option B: Standalone Image (Kubernetes / AWS ECS / Google Cloud Run)

1. **Build standalone container image:**
   ```bash
   docker build -f Dockerfile.standalone -t your-org/hindi-stt:latest .
   ```
2. **Push to container registry:**
   ```bash
   docker push your-org/hindi-stt:latest
   ```
3. **Deploy Web API Service:**
   ```bash
   docker run -d --name hindi-stt-web \
     -p 8000:8000 \
     -e API_KEY=your-production-key \
     -e REDIS_HOST=your-redis-host \
     your-org/hindi-stt:latest uvicorn src.api:app --host 0.0.0.0 --port 8000
   ```
4. **Deploy Worker Service (Scalable):**
   ```bash
   docker run -d --name hindi-stt-worker \
     -e REDIS_HOST=your-redis-host \
     your-org/hindi-stt:latest python run.py worker --workers 2
   ```

---

## Troubleshooting

### `API_KEY is not set` on startup
Ensure `API_KEY` is defined in `.env` or passed as an environment variable to the container.

### Models not found / `VOSK_MODEL_PATH` error
Run `bash scripts/download_models.sh` to ensure model files are present in `./models/vosk`.

### Cadence-Fast `Sequential has no attribute 'weight'`
Ensure you are using **Python 3.12** inside your virtual environment (`python --version`). Python 3.14 breaks Cadence.

### WebSocket handshake returns 401/403
Ensure `api_key` is passed in the query parameter (`/stream?api_key=<KEY>`) and matches the configured `API_KEY`.

### POST /transcribe returns 415 (Unsupported Media Type)
The uploaded file format is not supported. Supported extensions: `wav`, `mp3`, `mp4`, `mkv`, `avi`, `flac`, `ogg`, `webm`, `m4a`.

### POST /transcribe returns 413 (File Too Large)
The file exceeds `MAX_UPLOAD_MB` (default 200 MB). Increase `MAX_UPLOAD_MB` in `.env`.

### Docker container restarts or runs out of memory
Ensure Docker Desktop or host has at least **4 GB RAM** allocated. For low-memory environments, keep `PRELOAD_MODELS=false` on web container and run 1 Celery worker.