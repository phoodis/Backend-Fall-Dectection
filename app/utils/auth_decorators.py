from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity
from app.models.user import User, UserRole

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())
            user = User.query.get(current_user_id)
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            if not user.is_admin():
                return jsonify({'error': 'Admin access required'}), 403
            
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': f'Authorization failed: {str(e)}'}), 500
    
    return decorated_function

def admin_or_user(f):
    """Decorator to allow both admin and user roles"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            current_user_id = int(get_jwt_identity())
            user = User.query.get(current_user_id)
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            if not (user.is_admin() or user.is_user()):
                return jsonify({'error': 'Access denied'}), 403
            
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': f'Authorization failed: {str(e)}'}), 500
    
    return decorated_function

def get_current_user():
    """Helper function to get current user object"""
    try:
        current_user_id = int(get_jwt_identity())
        return User.query.get(current_user_id)
    except:
        return None
