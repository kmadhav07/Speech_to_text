"""
celeryconfig.py – Celery broker / backend / runtime settings.
"""

import src.config as config

# Broker (task queue) — Redis DB 0
broker_url = f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/0"

# Result backend — Redis DB 1
result_backend = f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/1"

# Connection retry
broker_connection_retry_on_startup = True

# Serialization
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]

# Reliability
task_acks_late = True
worker_prefetch_multiplier = 1
task_reject_on_worker_lost = True

# Visibility
task_track_started = True

# Results
result_expires = 86400

# Routing - UPDATED path for tasks
task_routes = {
    "src.celery_worker.tasks.transcribe_file_task": {"queue": "transcription"},
}

# Timezone
timezone = "UTC"
enable_utc = True