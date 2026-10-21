from flask import Blueprint, jsonify
from app import db
from app.config import Config
from app.models.detection_log import DetectionLog
from app.models.notification_history import NotificationHistory
from app.models.camera import Camera
from app.models.user import User
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, date
import pytz

tz = pytz.timezone('Asia/Bangkok')

bp = Blueprint('detection_logs', __name__, url_prefix='/api/detection-logs')

def _notification_dict(n):
    """One notification as the web UI reads it. The fields after image_path are the ones the friend's frontend
    expects; escalation / clip / still-down are NULL (or 0) here because nothing writes them yet."""
    return {
        'id': n.id,
        'camera_id': n.camera_id,
        'sent_at': n.sent_at.isoformat(),
        'detection_type': n.detection_type,
        'image_path': n.image_path,
        'confidence': n.confidence,
        'acknowledged_at': n.acknowledged_at.isoformat() if n.acknowledged_at else None,
        'acknowledged_by': n.acknowledged_by,
        'escalation_count': n.escalation_count or 0,
        'still_down_seconds': n.still_down_seconds,
        'still_down_threshold': Config.STILL_DOWN_SECONDS,
        'clip_path': n.clip_path
    }


@bp.route('', methods=['GET'])
@jwt_required()
def get_detection_logs():
    current_user_id = int(get_jwt_identity())
    user = User.query.get(current_user_id)
    
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    
    # Admin sees all logs, regular users see only their cameras
    if user and user.is_admin():
        detection_logs = DetectionLog.query.filter(
            DetectionLog.timestamp >= today_start,
            DetectionLog.timestamp <= today_end
        ).order_by(DetectionLog.timestamp.desc()).all()
    else:
        user_camera_ids = [c.id for c in Camera.query.filter_by(user_id=current_user_id).all()]
        detection_logs = DetectionLog.query.filter(
            DetectionLog.camera_id.in_(user_camera_ids),
            DetectionLog.timestamp >= today_start,
            DetectionLog.timestamp <= today_end
        ).order_by(DetectionLog.timestamp.desc()).all()
    
    if not detection_logs:
        return jsonify({'message': 'No detection logs found in the system.'}), 200
    return jsonify([
        {
            'id': detection_log.id,
            'timestamp': detection_log.timestamp.isoformat(),
            'camera_id': detection_log.camera_id,
            'detection_result': detection_log.detection_result,
            'confidence_score': detection_log.confidence_score,
            'camera_name': detection_log.camera_name,
            'room_name': detection_log.room_name,
            'risk_level': getattr(detection_log, 'risk_level', 'normal'),
            'person_count': getattr(detection_log, 'person_count', 0)
        } for detection_log in detection_logs
    ])

@bp.route('/<int:camera_id>', methods=['GET'])
@jwt_required()
def get_detection_logs_for_camera(camera_id):
    current_user_id = int(get_jwt_identity())
    user = User.query.get(current_user_id)
    
    # Admin can access any camera, users only their own
    if user and user.is_admin():
        camera = Camera.query.get(camera_id)
    else:
        camera = Camera.query.filter_by(id=camera_id, user_id=current_user_id).first()
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    
    detection_logs = DetectionLog.query.filter(
        DetectionLog.camera_id == camera_id,
        DetectionLog.timestamp >= today_start,
        DetectionLog.timestamp <= today_end
    ).order_by(DetectionLog.timestamp.desc()).all()
    
    if not detection_logs:
        return jsonify({'message': f'No detection logs found for camera with ID {camera_id}.'}), 200
    return jsonify([
        {
            'id': detection_log.id,
            'timestamp': detection_log.timestamp.isoformat(),
            'camera_id': detection_log.camera_id,
            'detection_result': detection_log.detection_result,
            'confidence_score': detection_log.confidence_score,
            'camera_name': detection_log.camera_name,
            'room_name': detection_log.room_name,
            'risk_level': getattr(detection_log, 'risk_level', 'normal'),
            'person_count': getattr(detection_log, 'person_count', 0)
        } for detection_log in detection_logs
    ])

@bp.route('/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    current_user_id = int(get_jwt_identity())
    user = User.query.get(current_user_id)
    
    # Admin sees all notifications, regular users see only their cameras
    if user and user.is_admin():
        notifications = NotificationHistory.query.order_by(NotificationHistory.sent_at.desc()).all()
    else:
        user_camera_ids = [c.id for c in Camera.query.filter_by(user_id=current_user_id).all()]
        notifications = NotificationHistory.query.filter(NotificationHistory.camera_id.in_(user_camera_ids)).order_by(NotificationHistory.sent_at.desc()).all()
    
    if not notifications:
        return jsonify({'message': 'No notification history found in the system.'}), 200
    return jsonify([_notification_dict(n) for n in notifications])

@bp.route('/notifications/<int:camera_id>', methods=['GET'])
@jwt_required()
def get_notifications_for_camera(camera_id):
    current_user_id = int(get_jwt_identity())
    user = User.query.get(current_user_id)
    
    # Admin can access any camera, users only their own
    if user and user.is_admin():
        camera = Camera.query.get(camera_id)
    else:
        camera = Camera.query.filter_by(id=camera_id, user_id=current_user_id).first()
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    notifications = NotificationHistory.query.filter_by(camera_id=camera_id).order_by(NotificationHistory.sent_at.desc()).all()
    if not notifications:
        return jsonify({'message': f'No notification history found for camera with ID {camera_id}.'}), 200
    return jsonify([_notification_dict(n) for n in notifications])


@bp.route('/notifications/<int:notification_id>/acknowledge', methods=['POST'])
@jwt_required()
def acknowledge_notification(notification_id):
    """Mark an alert as seen. A user may acknowledge alerts from their own cameras, an admin any alert.

    Idempotent, and the FIRST acknowledgement is the one that is kept: a second press (by the same person or
    another) answers 200 with the original acknowledged_at / acknowledged_by and writes nothing. The write is a
    single conditional UPDATE, so two presses at the same moment cannot both win."""
    current_user_id = int(get_jwt_identity())
    user = User.query.get(current_user_id)

    notification = NotificationHistory.query.get(notification_id)
    if not notification:
        return jsonify({'error': f'No notification found with ID {notification_id}.'}), 404

    if not (user and user.is_admin()):
        camera = Camera.query.filter_by(id=notification.camera_id, user_id=current_user_id).first()
        if not camera:
            return jsonify({'error': 'Not allowed to acknowledge this notification.'}), 403

    try:
        NotificationHistory.query.filter_by(id=notification_id, acknowledged_at=None).update(
            {'acknowledged_at': datetime.now(tz), 'acknowledged_by': current_user_id},
            synchronize_session=False)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to acknowledge notification: {str(e)}'}), 500

    db.session.expire_all()
    notification = NotificationHistory.query.get(notification_id)
    return jsonify({
        'id': notification.id,
        'acknowledged_at': notification.acknowledged_at.isoformat() if notification.acknowledged_at else None,
        'acknowledged_by': notification.acknowledged_by
    }), 200
