from app.models.notification_history import NotificationHistory
from app import db
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Bangkok')

def new_alert_image_path(prefix, camera_id, alert_dir=None):
    """Where to write a new alert picture. The file name ends in a random token, so it cannot be guessed from the
    camera id and the time: /api/alert-images/ has no login (the <img> tag and LINE cannot send one) and may be
    reachable from the internet through the LINE tunnel, so the name is the only secret protecting the picture.
    Files written before this keep their old names."""
    import os
    import secrets
    import time
    from app.config import Config
    directory = alert_dir or getattr(Config, 'ALERT_IMAGE_DIR', None) or '/app/tmp'
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{prefix}_{camera_id}_{int(time.time())}_{secrets.token_urlsafe(16)}.jpg")


def save_alert_log(camera_id, detection_type, image_path=None, additional_info=None, confidence=None):
    """
    Save alert log to database regardless of notification channel configuration

    Args:
        camera_id: ID of the camera
        detection_type: Type of detection (fall_red, bed_exit, etc.)
        image_path: Path to saved image (optional)
        additional_info: Additional information to log (optional)
        confidence: model score behind the alert (optional); when omitted and additional_info is a dict
            holding 'confidence', that value is stored

    Returns the saved NotificationHistory row (truthy), or False when it could not be saved; the failed
    transaction is rolled back so the shared session stays usable.
    """
    try:
        now = datetime.now(tz)

        if confidence is None and isinstance(additional_info, dict):
            confidence = additional_info.get('confidence')

        notif = NotificationHistory(
            camera_id=camera_id,
            sent_at=now,
            detection_type=detection_type,
            image_path=image_path,
            confidence=float(confidence) if confidence is not None else None
        )
        
        db.session.add(notif)
        db.session.commit()
        
        print(f"[Camera {camera_id}] Alert log saved: {detection_type} at {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if additional_info:
            print(f"[Camera {camera_id}] Additional info: {additional_info}")
            
        return notif
        
    except Exception as e:
        print(f"[Camera {camera_id}] Failed to save alert log: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return False

def get_alert_history(camera_id, limit=50):
    """
    Get alert history for a specific camera
    
    Args:
        camera_id: ID of the camera
        limit: Maximum number of records to return
        
    Returns:
        List of alert records
    """
    try:
        alerts = NotificationHistory.query.filter_by(camera_id=camera_id)\
                                         .order_by(NotificationHistory.sent_at.desc())\
                                         .limit(limit).all()
        
        return [{
            'id': alert.id,
            'camera_id': alert.camera_id,
            'detection_type': alert.detection_type,
            'sent_at': alert.sent_at.isoformat(),
            'image_path': alert.image_path
        } for alert in alerts]
        
    except Exception as e:
        print(f"Failed to get alert history for camera {camera_id}: {e}")
        return []

def get_alert_statistics(camera_id, days=7):
    """
    Get alert statistics for a camera over specified days
    
    Args:
        camera_id: ID of the camera
        days: Number of days to look back
        
    Returns:
        Dictionary with alert statistics
    """
    try:
        from datetime import timedelta
        
        start_date = datetime.now(tz) - timedelta(days=days)
        
        alerts = NotificationHistory.query.filter(
            NotificationHistory.camera_id == camera_id,
            NotificationHistory.sent_at >= start_date
        ).all()
        
        stats = {
            'total_alerts': len(alerts),
            'fall_red': 0,
            'fall_yellow': 0,
            'bed_exit': 0,
            'other': 0,
            'period_days': days,
            'start_date': start_date.isoformat(),
            'end_date': datetime.now(tz).isoformat()
        }
        
        for alert in alerts:
            if alert.detection_type == 'fall_red':
                stats['fall_red'] += 1
            elif alert.detection_type == 'fall_yellow':
                stats['fall_yellow'] += 1
            elif alert.detection_type == 'bed_exit':
                stats['bed_exit'] += 1
            else:
                stats['other'] += 1
        
        return stats
        
    except Exception as e:
        print(f"Failed to get alert statistics for camera {camera_id}: {e}")
        return None
