from celery import Celery

from app.config import settings

celery_app = Celery(
    "docparser",
    broker=str(settings.REDIS_URL),
    backend=str(settings.REDIS_URL),
    include=["app.tasks.parse_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
)

# Route tasks
celery_app.conf.task_routes = {
    "app.tasks.parse_tasks.parse_document_task": {"queue": "parsing"},
    "app.tasks.parse_tasks.retry_failed_documents": {"queue": "maintenance"},
}
