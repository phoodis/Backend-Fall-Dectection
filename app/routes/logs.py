from flask import Blueprint, jsonify
from app.models.detection_log import DetectionLog
from app.models.notification_history import NotificationHistory
from app.models.camera import Camera
from app.models.user import User
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, date

bp = Blueprint('detection_logs', __name__, url_prefix='/api/detection-logs')

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
    return jsonify([
        {
            'id': n.id,
            'camera_id': n.camera_id,
            'sent_at': n.sent_at.isoformat(),
            'detection_type': n.detection_type,
            'image_path': n.image_path
        } for n in notifications
    ])

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
    return jsonify([
        {
            'id': n.id,
            'camera_id': n.camera_id,
            'sent_at': n.sent_at.isoformat(),
            'detection_type': n.detection_type,
            'image_path': n.image_path
        } for n in notifications
    ]) 