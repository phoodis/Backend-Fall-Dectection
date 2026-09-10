from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.alert_service import get_alert_history, get_alert_statistics
from app.models.camera import Camera

bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')

def get_user_camera_or_404(camera_id, user_id):
    camera = Camera.query.filter_by(id=camera_id, user_id=user_id).first()
    if not camera:
        from flask import abort
        abort(404)
    return camera

@bp.route('/camera/<int:camera_id>/history', methods=['GET'])
@jwt_required()
def get_camera_alert_history(camera_id):
    """Get alert history for a specific camera"""
    current_user_id = int(get_jwt_identity())
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    limit = request.args.get('limit', 50, type=int)
    if limit > 200:  # Prevent excessive data requests
        limit = 200
    
    alerts = get_alert_history(camera_id, limit)
    
    return jsonify({
        'camera_id': camera_id,
        'camera_name': camera.name,
        'room_name': camera.room_name,
        'alerts': alerts,
        'total_returned': len(alerts)
    })

@bp.route('/camera/<int:camera_id>/statistics', methods=['GET'])
@jwt_required()
def get_camera_alert_statistics(camera_id):
    """Get alert statistics for a specific camera"""
    current_user_id = int(get_jwt_identity())
    camera = get_user_camera_or_404(camera_id, current_user_id)
    
    days = request.args.get('days', 7, type=int)
    if days > 90:  # Limit to 90 days
        days = 90
    
    stats = get_alert_statistics(camera_id, days)
    
    if stats is None:
        return jsonify({'error': 'Failed to get statistics'}), 500
    
    return jsonify({
        'camera_id': camera_id,
        'camera_name': camera.name,
        'room_name': camera.room_name,
        'statistics': stats
    })

@bp.route('/user/summary', methods=['GET'])
@jwt_required()
def get_user_alert_summary():
    """Get alert summary for all user cameras"""
    current_user_id = int(get_jwt_identity())
    
    cameras = Camera.query.filter_by(user_id=current_user_id).all()
    
    summary = {
        'total_cameras': len(cameras),
        'cameras': []
    }
    
    days = request.args.get('days', 7, type=int)
    if days > 90:
        days = 90
    
    for camera in cameras:
        stats = get_alert_statistics(camera.id, days)
        camera_info = {
            'camera_id': camera.id,
            'camera_name': camera.name,
            'room_name': camera.room_name,
            'detection_type': camera.detection_type,
            'is_active': camera.is_active,
            'statistics': stats
        }
        summary['cameras'].append(camera_info)
    
    return jsonify(summary)
