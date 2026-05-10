from celery import Celery
from kombu import Queue, Exchange  # ← Add this import
from app.config import settings

celery_app = Celery(
    "phos_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.standardize", "app.tasks.inference", "app.tasks.aggregate"]
)

# ← ADD THESE 3 LINES TO ROUTE TASKS TO "default" QUEUE
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

# Optional: Explicitly define the queue (more robust)
celery_app.conf.task_queues = (
    Queue("default", Exchange("default"), routing_key="default"),
)

# Memory-safe config (keep existing)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    worker_max_tasks_per_child=50,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)