from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.camera import Camera
from app import celery

bp = Blueprint('health', __name__, url_prefix='/api/health')

@bp.route('', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'The server is running and operational.'}), 200

@bp.route('/camera-detection-service', methods=['GET'])
@jwt_required()
def check_camera_detection_service():
    """
    Check the status of camera detection services.
    Returns overall service status and individual camera statuses.
    """
    current_user_id = int(get_jwt_identity())
    
    cameras = Camera.query.filter_by(user_id=current_user_id).all()
    
    if not cameras:
        return jsonify({
            'service_status': 'no_cameras',
            'message': 'No cameras configured for this user.',
            'total_cameras': 0,
            'active_cameras': 0,
            'inactive_cameras': 0,
            'cameras': []
        }), 200
    
    # Count active and inactive cameras
    active_cameras = []
    inactive_cameras = []
    
    for camera in cameras:
        camera_info = {
            'id': camera.id,
            'name': camera.name,
            'room_name': camera.room_name,
            'detection_type': camera.detection_type,
            'is_active': camera.is_active,
            'status': 'running' if camera.is_active else 'stopped'
        }
        
        if camera.is_active:
            active_cameras.append(camera_info)
        else:
            inactive_cameras.append(camera_info)
    
    # Determine overall service status
    total_cameras = len(cameras)
    active_count = len(active_cameras)
    inactive_count = len(inactive_cameras)
    
    if active_count == 0:
        service_status = 'all_stopped'
        message = 'All camera detection services are stopped.'
    elif inactive_count == 0:
        service_status = 'all_running'
        message = 'All camera detection services are running.'
    else:
        service_status = 'partially_running'
        message = f'{active_count} out of {total_cameras} camera detection services are running.'
    
    try:
        active_tasks = celery.control.inspect().active()
        celery_status = 'running' if active_tasks is not None else 'stopped'
    except Exception as e:
        celery_status = 'unknown'
    
    return jsonify({
        'service_status': service_status,
        'message': message,
        'celery_worker_status': celery_status,
        'total_cameras': total_cameras,
        'active_cameras': active_count,
        'inactive_cameras': inactive_count,
        'cameras': active_cameras + inactive_cameras
    }), 200 