FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (FFmpeg, build tools, audio libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg git wget libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

# Copy project
COPY . /app

# Ensure runtime dirs exist
RUN mkdir -p /app/outputs /app/data

EXPOSE 8000

CMD ["python", "run.py", "api"]
