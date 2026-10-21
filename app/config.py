import os
import tempfile
from datetime import timedelta

# v3 fall detector: the profile it was EVALUATED with (CPU, 320 px input, 8 fps, person-crop ROI 256,
# alert threshold 0.65 -- Dataset_clips + Le2i evaluation, Oct 2026). The detector reads these
# V3_* variables when app/detection/v3_fall_detection.py is imported, and its in-code defaults are
# a different, unmeasured configuration (960 px, no frame-rate cap), so they are set here, before
# anything imports it. setdefault: a real environment variable or .env entry still wins, but a
# value that differs from this table is a detector nobody has measured.
V3_EVALUATED_PROFILE = {
    "V3_POSE_MODEL": "yolo26s-pose.pt",
    "V3_CLASSIFIER": "fall_classifier_v3.onnx",
    "V3_IMGSZ": "320",
    "V3_TARGET_FPS": "8",
    "V3_ROI_IMGSZ": "256",
    "V3_ROI_FULL_EVERY": "8",
    "V3_THRESHOLD": "0.65",
    "V3_PARTIAL_MIN": "4",
    "V3_PREPROCESS": "auto",
    "V3_PREPROCESS_DARK_BELOW": "70",
}
for _key, _value in V3_EVALUATED_PROFILE.items():
    os.environ.setdefault(_key, _value)


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

    # Fall detector used by detection_type 'fall_v2' cameras.
    #   'v3' (default): YOLO-pose + temporal CNN (app/detection/v3_fall_detection.py)
    #   'v2'          : the original ONNX/MediaPipe detector, unchanged -- set FALL_DETECTOR=v2 to switch back
    FALL_DETECTOR = os.getenv("FALL_DETECTOR", "v3").strip().lower()
    # Directory holding fall_classifier_v3.onnx and the pose weights (V3_POSE_MODEL)
    V3_FALL_DETECTION_MODEL_DIR = os.getenv("V3_FALL_DETECTION_MODEL_DIR", "models")

    # Alert image storage
    ALERT_IMAGE_DIR = os.getenv("ALERT_IMAGE_DIR", "/app/tmp")

    # Live view (app/services/stream_service.py). Nothing here reaches the detector: the preview has its own
    # capture, and these only change what is sent to the browser.
    #   STREAM_MAX_SIDE      longest side of the picture in pixels (the camera's full size is shrunk to this)
    #   STREAM_JPEG_QUALITY  1-100
    #   STREAM_FPS           most frames per second sent to one viewer
    #   STREAM_OVERLAY_ENABLED       may a viewer ask for the pose skeleton (?overlay=1)? It loads a second copy
    #                                of the pose model into the web process and runs it for that viewer.
    #   STREAM_OVERLAY_INFER_EVERY   run the pose model on every Nth frame sent; the rest reuse the last result
    STREAM_MAX_SIDE = int(os.getenv('STREAM_MAX_SIDE', 640))
    STREAM_JPEG_QUALITY = int(os.getenv('STREAM_JPEG_QUALITY', 70))
    STREAM_FPS = float(os.getenv('STREAM_FPS', 10))
    STREAM_OVERLAY_ENABLED = os.getenv('STREAM_OVERLAY_ENABLED', 'false').strip().lower() in ('1', 'true', 'yes')
    STREAM_OVERLAY_INFER_EVERY = int(os.getenv('STREAM_OVERLAY_INFER_EVERY', 6))

    # Folder listed by GET /api/cameras/test-videos (video files a camera can use as its source). The path is as
    # seen by the process that runs the detector, i.e. inside the container.
    TEST_VIDEO_DIR = os.getenv('TEST_VIDEO_DIR', '/app/videos')

    # Reported to the web UI with every notification (it decides the "still on the floor" badge). Nothing in this
    # backend measures still-down yet, so the field it applies to stays NULL.
    STILL_DOWN_SECONDS = float(os.getenv("STILL_DOWN_SECONDS", 10))

    ALERT_START_TIME = os.getenv("ALERT_START_TIME", "00:00")
    ALERT_END_TIME = os.getenv("ALERT_END_TIME", "23:59")