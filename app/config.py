import os
import tempfile
from datetime import timedelta

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@db:5432/postgres')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-secret')
    
    # JWT Configuration
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)  # Access token expires in 1 hour
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)  # Refresh token expires in 7 days
    JWT_BLACKLIST_ENABLED = True
    JWT_BLACKLIST_TOKEN_CHECKS = ['access', 'refresh']
    
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
    
    # Celery Task Configuration
    task_time_limit = None  # No time limit for long-running detection tasks
    task_soft_time_limit = None  # No soft time limit
    worker_prefetch_multiplier = 1  # Only prefetch 1 task at a time
    task_acks_late = True  # Acknowledge tasks after completion
    worker_max_tasks_per_child = 1000  # Restart worker after 1000 tasks to prevent memory leaks

    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

    LOGGING_INTERVAL = int(os.getenv('LOGGING_INTERVAL', 60))
    LOG_RETENTION_DAYS = int(os.getenv('LOG_RETENTION_DAYS', 30))
    NOTIFICATION_COOLDOWN = int(os.getenv('NOTIFICATION_COOLDOWN', 60))
    AI_CONFIDENCE_THRESHOLD = float(os.getenv('AI_CONFIDENCE_THRESHOLD', 0.5))
    CAMERA_MAX_PARALLEL = int(os.getenv('CAMERA_MAX_PARALLEL', 8))
    CAMERA_MAX_PARALLEL_PER_TYPE = int(os.getenv('CAMERA_MAX_PARALLEL_PER_TYPE', 4))
    DEBUG = os.getenv('DEBUG', 'True') == 'True'
    PORT = int(os.getenv('PORT', 8932))

    # Detection model paths
    BED_EXIT_MODEL_PATH = os.getenv("BED_EXIT_MODEL_PATH", "models/bed_pose_mobilenetv2_3.onnx")
    FALL_DETECTION_MODEL_PATH = os.getenv("FALL_DETECTION_MODEL_PATH", "models/fall_detection_model.onnx")
    
    # V2 Fall Detection Model paths (ONNX)
    V2_FALL_DETECTION_MODEL_DIR = os.getenv("V2_FALL_DETECTION_MODEL_DIR", "models")
    V2_FALL_DETECTION_ONNX_PATH = os.getenv("V2_FALL_DETECTION_ONNX_PATH", "models/deepsvdd_model.onnx")
    V2_FALL_DETECTION_CENTER_PATH = os.getenv("V2_FALL_DETECTION_CENTER_PATH", "models/center.npy")
    V2_FALL_DETECTION_NORMALIZATION_PATH = os.getenv("V2_FALL_DETECTION_NORMALIZATION_PATH", "models/normalization.json")
    V2_FALL_DETECTION_THRESHOLD_PATH = os.getenv("V2_FALL_DETECTION_THRESHOLD_PATH", "models/threshold.json")

    # Alert image storage
    ALERT_IMAGE_DIR = os.getenv("ALERT_IMAGE_DIR", "/app/tmp")

    ALERT_START_TIME = os.getenv("ALERT_START_TIME", "00:00")
    ALERT_END_TIME = os.getenv("ALERT_END_TIME", "23:59")