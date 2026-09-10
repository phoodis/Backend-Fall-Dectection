import cv2
from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models.camera import Camera
from app.models.user import User, UserRole
from app.services.logging_service import save_system_log
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.camera_manager import process_camera, process_fall_detection, process_alone_detection, process_bed_exit_detection
from app.config import Config
import re

bp = Blueprint('cameras', __name__, url_prefix='/api/cameras')

def check_url(url):
    try:
        # Handle local HTTP URLs (from frontend)
        if url.startswith('http://localhost:3000/videos/'):
            filename = url.split('/')[-1]
            local_video_path = f"/app/videos/{filename}"
            
            # Check if the local file exists
            import os
            if not os.path.exists(local_video_path):
                print(f"Local video file does not exist: {local_video_path}")
                return False
            
            # Test the local file instead
            url = local_video_path
        
        # Check if it's a video file
        is_video_file = not url.startswith(('rtsp', 'rtmp')) and ('.' in url or 'localhost' in url)
        
        if is_video_file and not url.startswith('http'):
            import os
            # Check if file exists
            if not os.path.exists(url):
                print(f"Video file does not exist: {url}")
                return False
            
            # Check if it's a valid video file
            valid_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
            if not any(url.lower().endswith(ext) for ext in valid_extensions):
                print(f"Invalid video file extension: {url}")
                return False
        
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            print(f"Failed to open: {url}")
            return False
        
        ret, _ = cap.read()
        cap.release()
        
        if not ret:
            print(f"Failed to read first frame from: {url}")
            return False
            
        return True
        
    except Exception as e:
        print(f"Error checking URL {url}: {str(e)}")
        return False

def get_user_camera_or_404(camera_id, user_id):
    camera = Camera.query.filter_by(id=camera_id, user_id=user_id).first()
    if not camera:
        from flask import abort
        abort(404)
    return camera

def get_current_user():
    """Helper function to get current user"""
    current_user_id = int(get_jwt_identity())
    return User.query.get(current_user_id)

def is_admin_or_owner(camera_id, user_id):
    """Check if user is admin or owns the camera"""
    user = User.query.get(user_id)
    if user and user.is_admin():
        return True
    camera = Camera.query.get(camera_id)
    return camera and camera.user_id == user_id

@bp.route('', methods=['GET'])
@jwt_required()
def list_cameras():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Admin can see all cameras, users see only their own
    if current_user.is_admin():
        cameras = Camera.query.all()
        camera_list = [
            {
                'id': c.id,
                'name': c.name,
                'room_name': c.room_name,
                'url': c.url,
                'detection_type': c.detection_type,
                'is_active': c.is_active,
                'alert_start_time': c.alert_start_time,
                'alert_end_time': c.alert_end_time,
                'notification_cooldown': c.notification_cooldown,
                'ai_confidence_threshold': c.ai_confidence_threshold,
                'enable_alone_detection': getattr(c, 'enable_alone_detection', True),
                'owner': {
                    'id': c.user_id,
                    'username': User.query.get(c.user_id).username if User.query.get(c.user_id) else 'Unknown'
                }
            } for c in cameras
        ]
    else:
        cameras = Camera.query.filter_by(user_id=current_user.id).all()
        camera_list = [
            {
                'id': c.id,
                'name': c.name,
                'room_name': c.room_name,
                'url': c.url,
                'detection_type': c.detection_type,
                'is_active': c.is_active,
                'alert_start_time': c.alert_start_time,
                'alert_end_time': c.alert_end_time,
                'notification_cooldown': c.notification_cooldown,
                'ai_confidence_threshold': c.ai_confidence_threshold,
                'enable_alone_detection': getattr(c, 'enable_alone_detection', True),
                'user_id': c.user_id,  # เพิ่ม user_id เพื่อให้ Frontend กรองได้
                'owner_id': c.user_id  # เพิ่ม owner_id สำหรับความเข้ากันได้
            } for c in cameras
        ]
    
    return jsonify(camera_list)

@bp.route('', methods=['POST'])
@jwt_required()
def add_camera():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Only admin can add cameras
    if not current_user.is_admin():
        return jsonify({'error': 'Admin access required to add cameras'}), 403
    
    data = request.get_json()
    name = data.get('name')
    room_name = data.get('room_name')
    url = data.get('url')
    detection_type = data.get('detection_type')
    owner_id = data.get('owner_id', current_user.id)  # Admin can assign to other users
    alert_start_time = data.get('alert_start_time', Config.ALERT_START_TIME)
    alert_end_time = data.get('alert_end_time', Config.ALERT_END_TIME)
    notification_cooldown = data.get('notification_cooldown', Config.NOTIFICATION_COOLDOWN)
    ai_confidence_threshold = data.get('ai_confidence_threshold', Config.AI_CONFIDENCE_THRESHOLD)
    enable_alone_detection = data.get('enable_alone_detection', True)  # Default True

    time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
    for tval, label in [(alert_start_time, 'alert_start_time'), (alert_end_time, 'alert_end_time')]:
        if not time_pattern.match(tval):
            return jsonify({'error': f'{label} must be in HH:MM 24-hour format (e.g., 08:30, 20:15).'}), 400

    if not all([name, room_name, url, detection_type]):
        return jsonify({'error': 'All fields (name, room_name, url, detection_type) are required.'}), 400
    
    # Verify owner exists
    if owner_id != current_user.id:
        owner = User.query.get(owner_id)
        if not owner:
            return jsonify({'error': f'Owner user with ID {owner_id} not found'}), 400

    # if not check_url(url):
    #     return jsonify({'error': 'Unable to connect to the provided camera URL. Please verify the stream and try again.'}), 400

    camera = Camera(
        name=name,
        room_name=room_name,
        url=url,
        detection_type=detection_type,
        user_id=owner_id,
        alert_start_time=alert_start_time,
        alert_end_time=alert_end_time,
        notification_cooldown=notification_cooldown,
        ai_confidence_threshold=ai_confidence_threshold,
        enable_alone_detection=enable_alone_detection
    )
    db.session.add(camera)
    db.session.commit()
    save_system_log('INFO', f'Camera added by admin: {camera.name} in {camera.room_name} for user {owner_id}', 'CAMERA', current_user.id)
    return jsonify({'message': f'Camera "{camera.name}" was successfully added.', 'id': camera.id}), 201

@bp.route('/<int:id>', methods=['PUT'])
@jwt_required()
def update_camera(id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Only admin can update cameras
    if not current_user.is_admin():
        return jsonify({'error': 'Admin access required to update cameras'}), 403
    
    camera = Camera.query.get_or_404(id)
    data = request.get_json()
    
    for field in ['name', 'room_name', 'url', 'detection_type', 'alert_start_time', 'alert_end_time', 'notification_cooldown', 'ai_confidence_threshold', 'enable_alone_detection']:
        if field in data:
            if field in ['alert_start_time', 'alert_end_time']:
                time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
                if not time_pattern.match(data[field]):
                    return jsonify({'error': f'{field} must be in HH:MM 24-hour format (e.g., 08:30, 20:15).'}), 400
            setattr(camera, field, data[field])
    
    # Allow admin to change camera owner
    if 'owner_id' in data:
        owner = User.query.get(data['owner_id'])
        if not owner:
            return jsonify({'error': f'Owner user with ID {data["owner_id"]} not found'}), 400
        camera.user_id = data['owner_id']
    
    db.session.commit()
    save_system_log('INFO', f'Camera updated by admin: {camera.name}', 'CAMERA', current_user.id)
    return jsonify({'message': f'Camera "{camera.name}" was updated successfully.'})

@bp.route('/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_camera(id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Only admin can delete cameras
    if not current_user.is_admin():
        return jsonify({'error': 'Admin access required to delete cameras'}), 403
    
    camera = Camera.query.get_or_404(id)
    camera_name = camera.name
    camera_room = camera.room_name
    db.session.delete(camera)
    db.session.commit()
    save_system_log('INFO', f'Camera deleted by admin: {camera_name} from {camera_room}', 'CAMERA', current_user.id)
    return jsonify({'message': f'Camera "{camera_name}" was deleted successfully.'})

@bp.route('/<int:id>/status', methods=['GET'])
@jwt_required()
def get_camera_status(id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    camera = Camera.query.get_or_404(id)
    
    # Users can only view their own cameras, admins can view all
    if not current_user.is_admin() and camera.user_id != current_user.id:
        return jsonify({'error': 'Access denied. You can only view your own cameras.'}), 403
    
    # Get the latest detection log to show last activity
    from app.models.detection_log import DetectionLog
    latest_log = DetectionLog.query.filter_by(camera_id=camera.id).order_by(DetectionLog.timestamp.desc()).first()
    
    status_info = {
        'camera_id': camera.id,
        'camera_name': camera.name,
        'room_name': camera.room_name,
        'detection_type': camera.detection_type,
        'is_active': camera.is_active,
        'status': 'running' if camera.is_active else 'stopped',
        'message': f'Detection service is {"running" if camera.is_active else "stopped"} for camera "{camera.name}"',
        'configuration': {
            'alert_start_time': camera.alert_start_time,
            'alert_end_time': camera.alert_end_time,
            'notification_cooldown': camera.notification_cooldown,
            'ai_confidence_threshold': camera.ai_confidence_threshold
        }
    }
    
    # Add owner information if admin is viewing
    if current_user.is_admin():
        owner = User.query.get(camera.user_id)
        status_info['owner'] = {
            'id': camera.user_id,
            'username': owner.username if owner else 'Unknown'
        }
    
    # Add last activity information if available
    if latest_log:
        status_info['last_activity'] = {
            'timestamp': latest_log.timestamp.isoformat(),
            'detection_result': latest_log.detection_result,
            'confidence': latest_log.confidence_score
        }
    else:
        status_info['last_activity'] = None
    
    return jsonify(status_info), 200

@bp.route('/<int:id>/start', methods=['POST'])
@jwt_required()
def start_camera(id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    camera = Camera.query.get_or_404(id)
    
    # Users can only start their own cameras, admins can start all
    if not current_user.is_admin() and camera.user_id != current_user.id:
        return jsonify({'error': 'Access denied. You can only control your own cameras.'}), 403
    
    if camera.is_active:
        return jsonify({'message': f'Monitoring for camera "{camera.name}" is already running.'}), 200
    
    # For regular users, enforce CAMERA_MAX_PARALLEL limit per user
    # For admins, check global limit or per-user limit based on camera owner
    if current_user.is_admin():
        # Check limit for the camera owner
        owner_id = camera.user_id
        active_cameras = Camera.query.filter_by(user_id=owner_id, is_active=True).count()
    else:
        # Check limit for current user
        owner_id = current_user.id
        active_cameras = Camera.query.filter_by(user_id=current_user.id, is_active=True).count()
    
    if active_cameras >= Config.CAMERA_MAX_PARALLEL:
        return jsonify({'error': f'Maximum number of active cameras ({Config.CAMERA_MAX_PARALLEL}) reached for the camera owner. Please stop another camera before starting a new one.'}), 400
    
    camera.is_active = True
    db.session.commit()
    
    # Start appropriate Celery tasks based on detection type
    config = {
        "BED_EXIT_MODEL_PATH": Config.BED_EXIT_MODEL_PATH,
        "FALL_DETECTION_MODEL_PATH": Config.FALL_DETECTION_MODEL_PATH,
        "V2_FALL_DETECTION_MODEL_DIR": Config.V2_FALL_DETECTION_MODEL_DIR,
        "V2_FALL_DETECTION_ONNX_PATH": Config.V2_FALL_DETECTION_ONNX_PATH,
        "V2_FALL_DETECTION_CENTER_PATH": Config.V2_FALL_DETECTION_CENTER_PATH,
        "V2_FALL_DETECTION_NORMALIZATION_PATH": Config.V2_FALL_DETECTION_NORMALIZATION_PATH,
        "V2_FALL_DETECTION_THRESHOLD_PATH": Config.V2_FALL_DETECTION_THRESHOLD_PATH,
        "LOGGING_INTERVAL": Config.LOGGING_INTERVAL,
    }
    
    task_ids = []
    
    if camera.detection_type == 'bed_exit':
        task = process_bed_exit_detection.apply_async(args=[camera.id, config])
        task_ids.append(task.id)
        save_system_log('INFO', f'Bed exit detection task started for camera {camera.name}', 'CAMERA', current_user.id)
    elif camera.detection_type == 'fall':
        # Start both fall and alone detection as separate tasks
        fall_task = process_fall_detection.apply_async(args=[camera.id, config])
        alone_task = process_alone_detection.apply_async(args=[camera.id, config])
        task_ids.extend([fall_task.id, alone_task.id])
        save_system_log('INFO', f'Fall and alone detection tasks started for camera {camera.name}', 'CAMERA', current_user.id)
    elif camera.detection_type == 'fall_v2':
        from app.services.camera_manager import process_v2_fall_detection, process_v2_alone_detection
        fall_v2_task = process_v2_fall_detection.apply_async(args=[camera.id, config])
        alone_v2_task = process_v2_alone_detection.apply_async(args=[camera.id, config])
        task_ids.extend([fall_v2_task.id, alone_v2_task.id])
        save_system_log('INFO', f'V2 Fall and alone detection tasks started for camera {camera.name}', 'CAMERA', current_user.id)
    else:
        task = process_fall_detection.apply_async(args=[camera.id, config])
        task_ids.append(task.id)
        save_system_log('INFO', f'Fall detection task started for camera {camera.name}', 'CAMERA', current_user.id)
    
    response_message = f'Monitoring for camera "{camera.name}" has started.'
    if len(task_ids) > 1:
        response_message += f' Running {len(task_ids)} parallel detection tasks.'
    
    return jsonify({
        'message': response_message,
        'task_ids': task_ids,
        'detection_type': camera.detection_type
    })

@bp.route('/<int:id>/stop', methods=['POST'])
@jwt_required()
def stop_camera(id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    camera = Camera.query.get_or_404(id)
    
    # Users can only stop their own cameras, admins can stop all
    if not current_user.is_admin() and camera.user_id != current_user.id:
        return jsonify({'error': 'Access denied. You can only control your own cameras.'}), 403
    
    if not camera.is_active:
        return jsonify({'message': f'Monitoring for camera "{camera.name}" is already stopped.'}), 200
    
    camera.is_active = False
    db.session.commit()
    save_system_log('INFO', f'Camera stopped: {camera.name}', 'CAMERA', current_user.id)
    # The running Celery task will exit on its own
    return jsonify({'message': f'Monitoring for camera "{camera.name}" has been stopped.'})

@bp.route('/<int:id>', methods=['GET'])
@jwt_required()
def get_camera(id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 404
    
    camera = Camera.query.get_or_404(id)
    
    # Users can only view their own cameras, admins can view all
    if not current_user.is_admin() and camera.user_id != current_user.id:
        return jsonify({'error': 'Access denied. You can only view your own cameras.'}), 403
    
    camera_data = {
        'id': camera.id,
        'name': camera.name,
        'room_name': camera.room_name,
        'url': camera.url,
        'detection_type': camera.detection_type,
        'is_active': camera.is_active,
        'alert_start_time': camera.alert_start_time,
        'alert_end_time': camera.alert_end_time,
        'notification_cooldown': camera.notification_cooldown,
        'ai_confidence_threshold': camera.ai_confidence_threshold
    }
    
    # Add owner information if admin is viewing
    if current_user.is_admin():
        owner = User.query.get(camera.user_id)
        camera_data['owner'] = {
            'id': camera.user_id,
            'username': owner.username if owner else 'Unknown'
        }
    
    return jsonify(camera_data) 