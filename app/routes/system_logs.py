from flask import Blueprint, jsonify, request
from app import db
from app.models.system_log import SystemLog
from app.models.user import User
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, date

bp = Blueprint('system_logs', __name__, url_prefix='/api/system-logs')

@bp.route('', methods=['GET'])
@jwt_required()
def get_system_logs():
    current_user_id = int(get_jwt_identity())
    
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    level = request.args.get('level')
    component = request.args.get('component')
    
    query = SystemLog.query
    
    if level:
        query = query.filter(SystemLog.level == level)
    if component:
        query = query.filter(SystemLog.component == component)
    
    system_logs = query.order_by(SystemLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'logs': [
            {
                'id': log.id,
                'timestamp': log.timestamp.isoformat(),
                'level': log.level,
                'message': log.message,
                'component': log.component,
                'user_id': log.user_id
            } for log in system_logs.items
        ],
        'total': system_logs.total,
        'pages': system_logs.pages,
        'current_page': page
    })

@bp.route('/levels', methods=['GET'])
@jwt_required()
def get_log_levels():
    return jsonify(['INFO', 'WARNING', 'ERROR', 'CRITICAL'])

@bp.route('/components', methods=['GET'])
@jwt_required()
def get_log_components():
    components = db.session.query(SystemLog.component).distinct().all()
    return jsonify([comp[0] for comp in components])
