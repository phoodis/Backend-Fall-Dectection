import os
os.environ['CELERY_WORKER'] = 'true'

from app import create_app, celery
from app.services.logging_service import cleanup_old_logs
from celery.schedules import crontab

app = create_app()
app.app_context().push()

# Models will be loaded lazily when detection tasks start
# This prevents unnecessary pre-loading and memory usage
print("[Celery Worker] Ready - Models will load on-demand")

@celery.task
def cleanup_logs_task():
    cleanup_old_logs()
    return "Log cleanup completed"

celery.conf.beat_schedule = {
    'cleanup-logs-daily': {
        'task': 'celery_worker.cleanup_logs_task',
        'schedule': crontab(hour=2, minute=0),
    },
}

celery.conf.timezone = 'Asia/Bangkok' 