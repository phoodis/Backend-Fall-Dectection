from flask import Blueprint, Response, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from app.models.camera import Camera
from app.services.stream_service import (
    stream_manager, 
    generate_mjpeg_stream, 
    get_stream_stats,
    cleanup_streams
)
from app.services.logging_service import save_system_log

bp = Blueprint('stream', __name__, url_prefix='/api/stream')


def get_user_camera_or_404(camera_id, user_id=None):
    """Helper function to get camera with optional user verification"""
    if user_id:
        camera = Camera.query.filter_by(id=camera_id, user_id=user_id).first()
    else:
        # For testing without auth, get any camera with this ID
        camera = Camera.query.get(camera_id)
    if not camera:
        return None
    return camera


def get_current_user_id():
    """Get current user ID from JWT token if available"""
    try:
        verify_jwt_in_request(optional=True)
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except:
        return None


@bp.route('/camera/<int:camera_id>', methods=['GET'])
def stream_camera(camera_id):
    """
    Stream video from a specific camera as MJPEG
    Returns: MJPEG video stream
    """
    current_user_id = get_current_user_id()
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    try:
        # Log stream access
        save_system_log('INFO', f'Video stream accessed for camera {camera.name}', 'STREAM', current_user_id)
        
        # Generate MJPEG stream
        return Response(
            generate_mjpeg_stream(camera_id, camera.url, camera.name),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization'
            }
        )
        
    except Exception as e:
        save_system_log('ERROR', f'Stream error for camera {camera.name}: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': f'Failed to start stream for camera {camera_id}'}), 500


@bp.route('/camera/<int:camera_id>/start', methods=['POST'])
def start_camera_stream(camera_id):
    """
    Start a camera stream
    """
    current_user_id = get_current_user_id()
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    try:
        stream = stream_manager.streams.get(camera_id)
        if stream and stream.is_active():
            return jsonify({
                'message': f'Stream for camera "{camera.name}" is already active.',
                'camera_id': camera_id,
                'status': 'active'
            })
        
        # This will create and start the stream
        stream = stream_manager.get_stream(camera_id, camera.url, camera.name)
        if stream:
            save_system_log('INFO', f'Stream started for camera {camera.name}', 'STREAM', current_user_id)
            return jsonify({
                'message': f'Stream started for camera "{camera.name}".',
                'camera_id': camera_id,
                'status': 'started'
            })
        else:
            return jsonify({'error': f'Failed to start stream for camera {camera_id}'}), 500
            
    except Exception as e:
        save_system_log('ERROR', f'Error starting stream for camera {camera.name}: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': f'Failed to start stream for camera {camera_id}'}), 500


@bp.route('/camera/<int:camera_id>/stop', methods=['POST'])
def stop_camera_stream(camera_id):
    """
    Stop a camera stream
    """
    current_user_id = get_current_user_id()
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    try:
        success = stream_manager.stop_stream(camera_id)
        if success:
            save_system_log('INFO', f'Stream stopped for camera {camera.name}', 'STREAM', current_user_id)
            return jsonify({
                'message': f'Stream stopped for camera "{camera.name}".',
                'camera_id': camera_id,
                'status': 'stopped'
            })
        else:
            return jsonify({
                'message': f'No active stream found for camera "{camera.name}".',
                'camera_id': camera_id,
                'status': 'not_found'
            })
            
    except Exception as e:
        save_system_log('ERROR', f'Error stopping stream for camera {camera.name}: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': f'Failed to stop stream for camera {camera_id}'}), 500


@bp.route('/camera/<int:camera_id>/status', methods=['GET'])
def get_camera_stream_status(camera_id):
    """
    Get the status of a camera stream
    """
    current_user_id = get_current_user_id()
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    try:
        stream = stream_manager.streams.get(camera_id)
        if stream:
            stats = stream.get_stats()
            return jsonify({
                'camera_id': camera_id,
                'camera_name': camera.name,
                'is_streaming': stream.is_active(),
                'stats': stats
            })
        else:
            return jsonify({
                'camera_id': camera_id,
                'camera_name': camera.name,
                'is_streaming': False,
                'stats': None
            })
            
    except Exception as e:
        save_system_log('ERROR', f'Error getting stream status for camera {camera.name}: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': f'Failed to get stream status for camera {camera_id}'}), 500


@bp.route('/stats', methods=['GET'])
def get_all_stream_stats():
    """
    Get statistics for all active streams
    """
    current_user_id = get_current_user_id()
    
    try:
        # If user is authenticated, only return their cameras
        if current_user_id:
            user_cameras = Camera.query.filter_by(user_id=current_user_id).all()
            user_camera_ids = [camera.id for camera in user_cameras]
        else:
            # For testing without auth, return all cameras
            all_cameras = Camera.query.all()
            user_camera_ids = [camera.id for camera in all_cameras]
        
        all_stats = get_stream_stats()
        
        # Filter stats to only include user's cameras
        user_streams = []
        for stream_stat in all_stats['streams']:
            if stream_stat['camera_id'] in user_camera_ids:
                user_streams.append(stream_stat)
        
        return jsonify({
            'active_streams': len(user_streams),
            'streams': user_streams,
            'total_system_streams': all_stats['active_streams']
        })
        
    except Exception as e:
        save_system_log('ERROR', f'Error getting stream stats: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': 'Failed to get stream statistics'}), 500


@bp.route('/cleanup', methods=['POST'])
def cleanup_inactive_streams():
    """
    Cleanup inactive streams (maintenance endpoint)
    """
    current_user_id = get_current_user_id()
    
    try:
        # Get count before cleanup
        before_count = len(stream_manager.get_active_streams())
        
        # Perform cleanup
        cleanup_streams()
        
        # Get count after cleanup
        after_count = len(stream_manager.get_active_streams())
        cleaned_count = before_count - after_count
        
        save_system_log('INFO', f'Stream cleanup completed: {cleaned_count} streams cleaned', 'STREAM', current_user_id)
        
        return jsonify({
            'message': 'Stream cleanup completed',
            'streams_cleaned': cleaned_count,
            'active_streams': after_count
        })
        
    except Exception as e:
        save_system_log('ERROR', f'Error during stream cleanup: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': 'Failed to cleanup streams'}), 500


# Utility endpoint for testing stream connectivity
@bp.route('/camera/<int:camera_id>/test', methods=['GET'])
def test_camera_stream(camera_id):
    """
    Test camera stream connectivity without starting a full stream
    """
    current_user_id = get_current_user_id()
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    if not camera:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    
    try:
        import cv2
        
        # Process URL same way as stream service
        processed_url = camera.url
        if camera.url.startswith('http://localhost:3000/videos/'):
            filename = camera.url.split('/')[-1]
            processed_url = f"/app/videos/{filename}"
        elif '\\' in camera.url and 'videos' in camera.url:
            filename = camera.url.split('\\')[-1]
            processed_url = f"/app/videos/{filename}"
        elif 'videos/' in camera.url and not camera.url.startswith('/app/videos/'):
            filename = camera.url.split('/')[-1]
            processed_url = f"/app/videos/{filename}"
        
        # Test connection
        cap = cv2.VideoCapture(processed_url)
        if not cap.isOpened():
            return jsonify({
                'camera_id': camera_id,
                'camera_name': camera.name,
                'url': camera.url,
                'processed_url': processed_url,
                'status': 'failed',
                'message': 'Unable to open video source'
            }), 400
        
        # Try to read a frame
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return jsonify({
                'camera_id': camera_id,
                'camera_name': camera.name,
                'url': camera.url,
                'processed_url': processed_url,
                'status': 'failed',
                'message': 'Unable to read frame from video source'
            }), 400
        
        # Get frame dimensions
        height, width = frame.shape[:2] if frame is not None else (0, 0)
        
        return jsonify({
            'camera_id': camera_id,
            'camera_name': camera.name,
            'url': camera.url,
            'processed_url': processed_url,
            'status': 'success',
            'message': 'Camera stream is accessible',
            'frame_info': {
                'width': width,
                'height': height,
                'channels': frame.shape[2] if len(frame.shape) > 2 else 1
            }
        })
        
    except Exception as e:
        return jsonify({
            'camera_id': camera_id,
            'camera_name': camera.name,
            'url': camera.url,
            'status': 'error',
            'message': f'Error testing camera stream: {str(e)}'
        }), 500
