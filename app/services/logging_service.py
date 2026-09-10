from app import db
from app.models.detection_log import DetectionLog
from app.models.system_log import SystemLog
from datetime import datetime, timedelta
import pytz
tz = pytz.timezone('Asia/Bangkok')
from app.models.camera import Camera

def save_detection_log(camera_id, detection_result, confidence_score, risk_level='normal', person_count=0):
    camera = Camera.query.get(camera_id)
    
    if detection_result in ['no_fall', 'normal', 'no_person'] and risk_level == 'normal':
        last_log = DetectionLog.query.filter_by(camera_id=camera_id).order_by(DetectionLog.timestamp.desc()).first()
        if last_log and last_log.detection_result == detection_result and last_log.risk_level == risk_level:
            return
    
    log = DetectionLog(
        camera_id=camera_id,
        detection_result=detection_result,
        confidence_score=confidence_score,
        camera_name=camera.name,
        room_name=camera.room_name,
        risk_level=risk_level,
        person_count=person_count,
        timestamp=datetime.now(tz)
    )
    db.session.add(log)
    db.session.commit()

def save_system_log(level, message, component, user_id=None):
    log = SystemLog(
        level=level,
        message=message,
        component=component,
        user_id=user_id,
        timestamp=datetime.now(tz)
    )
    db.session.add(log)
    db.session.commit()

def cleanup_detection_logs(retention_days=30):
    cutoff = datetime.now(tz) - timedelta(days=retention_days)
    DetectionLog.query.filter(DetectionLog.timestamp < cutoff).delete()
    db.session.commit()

def cleanup_system_logs(retention_days=90):
    cutoff = datetime.now(tz) - timedelta(days=retention_days)
    SystemLog.query.filter(SystemLog.timestamp < cutoff).delete()
    db.session.commit()

def cleanup_old_logs():
    cleanup_detection_logs(30)
    cleanup_system_logs(90) 