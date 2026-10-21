from flask import Blueprint, Response, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from app.models.camera import Camera
from app.services.stream_service import (
    stream_manager,
    generate_mjpeg_stream,
    get_stream_stats,
    cleanup_streams
)
from app.services.logging_service import save_system_log
from app.config import Config
from app.services.authz import admin_required
from app.services import media_token

# Query-string media tokens must never reach the request log.
media_token.install_log_redaction()

bp = Blueprint('stream', __name__, url_prefix='/api/stream')


def current_user_id_int():
    """-> the verified caller's id as an int, or None.

    JWT identities are strings here (`create_access_token(identity=str(user.id))`) and `Camera.user_id`
    is an integer column, so a raw identity is never handed to a filter.
    """
    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError):
        return None


def get_owned_camera(camera_id):
    """-> the camera, only if the caller's verified token owns it (or the caller is an admin), else None.

    Needs a route that has already demanded a token (@jwt_required). There is no anonymous branch: this used to
    fall back to `Camera.query.get(camera_id)` "for testing without auth", and since no stream route required a
    token that fallback was the normal path -- any request reached any camera by id.
    """
    user_id = current_user_id_int()
    if user_id is None:
        return None

    from app.models.user import User
    user = User.query.get(user_id)
    if not user:
        return None
    if user.is_admin():
        return Camera.query.get(camera_id)
    return Camera.query.filter_by(id=camera_id, user_id=user_id).first()


def camera_denied(camera_id):
    """The answer when get_owned_camera() found nothing: 404 if there is no such camera, 403 if there is one
    and it belongs to somebody else."""
    if Camera.query.get(camera_id) is None:
        return jsonify({'error': f'No camera found with ID {camera_id}.'}), 404
    return jsonify({'error': 'You do not have access to this camera.'}), 403


@bp.route('/camera/<int:camera_id>/media-token', methods=['POST'])
@jwt_required()
def issue_media_token(camera_id):
    """A short-lived credential for the live view of ONE camera -- see app/services/media_token.

    Requires the normal login and ownership (admins excepted); the token it returns can then be put in an
    <img src>, which cannot carry an Authorization header.
    """
    camera = get_owned_camera(camera_id)
    if not camera:
        return camera_denied(camera_id)
    token = media_token.issue(current_user_id_int(), camera_id, get_jwt().get('jti'))
    resp = jsonify({'token': token, 'expires_in': media_token.START_SECONDS,
                    'max_view_seconds': media_token.STREAM_MAX_SECONDS,
                    # whether ?overlay=1 will be honoured, so the UI can say so instead of doing nothing
                    'overlay_available': bool(Config.STREAM_OVERLAY_ENABLED)})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@bp.route('/camera/<int:camera_id>', methods=['GET'])
def stream_camera(camera_id):
    """
    Stream video from a specific camera as MJPEG, to the holder of a media token (?t=).

    The login JWT is NOT accepted here (a `?token=<jwt>` is ignored and the request is refused): the token must
    come from POST .../media-token. It is checked in full at connect time and before any camera work, and the
    view ends after media_token.STREAM_MAX_SECONDS; the client fetches a fresh token and reconnects.
    """
    camera, status = media_token.verify(request.args.get('t'), camera_id)
    if camera is None:
        return jsonify({'error': 'Not authorised to view this camera.'}), status

    try:
        # Opening a video element is a page view, not a system event, and the dashboard reconnects constantly,
        # so it is not written to the system log; stream failures are (below).
        deadline = media_token.view_deadline()
        draw_overlay = (request.args.get('overlay') in ('1', 'true')) and Config.STREAM_OVERLAY_ENABLED
        # No CORS headers: an <img> does not need them (app/__init__ also strips the ones flask-cors adds).
        return Response(
            media_token.bounded(
                generate_mjpeg_stream(camera_id, camera.url, camera.name, draw_overlay=draw_overlay, stop_at=deadline),
                deadline),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
            }
        )

    except Exception as e:
        save_system_log('ERROR', f'Stream error for camera {camera.name}: {str(e)}', 'STREAM', camera.user_id)
        return jsonify({'error': f'Failed to start stream for camera {camera_id}'}), 500


@bp.route('/camera/<int:camera_id>/start', methods=['POST'])
@jwt_required()
def start_camera_stream(camera_id):
    """
    Start a camera stream
    """
    current_user_id = current_user_id_int()
    camera = get_owned_camera(camera_id)

    if not camera:
        return camera_denied(camera_id)

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
@jwt_required()
def stop_camera_stream(camera_id):
    """
    Stop a camera stream
    """
    current_user_id = current_user_id_int()
    camera = get_owned_camera(camera_id)

    if not camera:
        return camera_denied(camera_id)

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
@jwt_required()
def get_camera_stream_status(camera_id):
    """
    Get the status of a camera stream
    """
    current_user_id = current_user_id_int()
    camera = get_owned_camera(camera_id)

    if not camera:
        return camera_denied(camera_id)

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
@jwt_required()
def get_all_stream_stats():
    """
    Statistics for the active streams the caller may see: their own cameras, or every camera for an admin.
    """
    current_user_id = current_user_id_int()
    if current_user_id is None:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from app.models.user import User
        user = User.query.get(current_user_id)
        if user is not None and user.is_admin():
            user_camera_ids = [camera.id for camera in Camera.query.all()]
        else:
            user_camera_ids = [camera.id for camera in Camera.query.filter_by(user_id=current_user_id).all()]

        all_stats = get_stream_stats()

        user_streams = [s for s in all_stats['streams'] if s['camera_id'] in user_camera_ids]

        # 'total_system_streams' (a count of every stream on the box, other users' included) is no longer
        # returned: it said nothing about the caller's own cameras and something about everyone else's.
        return jsonify({
            'active_streams': len(user_streams),
            'streams': user_streams,
        })

    except Exception as e:
        save_system_log('ERROR', f'Error getting stream stats: {str(e)}', 'STREAM', current_user_id)
        return jsonify({'error': 'Failed to get stream statistics'}), 500


@bp.route('/cleanup', methods=['POST'])
@jwt_required()
@admin_required
def cleanup_inactive_streams():
    """
    Cleanup inactive streams (maintenance endpoint).

    Admin-only: cleanup_streams() is global -- it walks every stream on the host and stops the inactive ones
    whoever owns them, so a login alone is not enough.
    """
    current_user_id = current_user_id_int()

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
@jwt_required()
def test_camera_stream(camera_id):
    """
    Test camera stream connectivity without starting a full stream
    """
    camera = get_owned_camera(camera_id)

    if not camera:
        return camera_denied(camera_id)

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
