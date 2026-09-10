from flask import Blueprint, request, jsonify
from app import db
from app.models.user import User, UserRole
from app.models.token_blocklist import TokenBlocklist
from app.services.logging_service import save_system_log
from flask_jwt_extended import (
    create_access_token, 
    create_refresh_token, 
    jwt_required, 
    get_jwt_identity, 
    get_jwt,
    decode_token
)
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Bangkok')
bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')  # Default to user role
    
    if not username or not password:
        return jsonify({'error': 'Both username and password are required to register a new account.'}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': f'The username "{username}" is already taken. Please choose a different username.'}), 409
    
    # Convert role string to enum
    try:
        user_role = UserRole.ADMIN if role.lower() == 'admin' else UserRole.USER
    except:
        user_role = UserRole.USER
    
    # Only allow admin creation if there are no existing admins (first admin)
    existing_admins = User.query.filter_by(role=UserRole.ADMIN).count()
    if user_role == UserRole.ADMIN and existing_admins > 0:
        # Check if current user is admin (for subsequent admin creation)
        try:
            current_user_id = get_jwt_identity()
            if current_user_id:
                current_user = User.query.get(int(current_user_id))
                if not current_user or not current_user.is_admin():
                    return jsonify({'error': 'Only existing admins can create new admin accounts.'}), 403
            else:
                return jsonify({'error': 'Only existing admins can create new admin accounts.'}), 403
        except:
            return jsonify({'error': 'Only existing admins can create new admin accounts.'}), 403
    
    user = User(username=username, role=user_role)
    user.telegram_chat_id = data.get('telegram_chat_id')  # ✅ เพิ่มตรงนี้
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    save_system_log('INFO', f'New user registered: {username} with role: {user_role.value}', 'AUTH', user.id)

    return jsonify({
        'message': 'User registered successfully',
        'user': user.to_dict()
    }), 201

@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        save_system_log('WARNING', f'Failed login attempt for username: {username}', 'AUTH')
        return jsonify({'error': 'The username or password you entered is incorrect. Please try again.'}), 401
    
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    save_system_log('INFO', f'User logged in: {username} with role: {user.role.value}', 'AUTH', user.id)
    
    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': user.to_dict()
    }), 200

@bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token using refresh token"""
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        new_access_token = create_access_token(identity=str(user.id))
        
        return jsonify({
            'access_token': new_access_token,
            'user': user.to_dict()
        }), 200
    except Exception as e:
        return jsonify({'error': f'Token refresh failed: {str(e)}'}), 500

@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout and blacklist current access token"""
    try:
        token = get_jwt()
        jti = token['jti']
        token_type = token['type']
        user_id = get_jwt_identity()
        expires_at = datetime.fromtimestamp(token['exp'], tz=tz)
        
        TokenBlocklist.add_token_to_blacklist(jti, token_type, user_id, expires_at)
        
        return jsonify({'message': 'You have been successfully logged out.'}), 200
    except Exception as e:
        return jsonify({'error': f'Logout failed: {str(e)}'}), 500

@bp.route('/logout-all', methods=['POST'])
@jwt_required()
def logout_all():
    """Logout from all devices by blacklisting both access and refresh tokens"""
    try:
        token = get_jwt()
        user_id = get_jwt_identity()
        
        current_jti = token['jti']
        current_type = token['type']
        current_expires_at = datetime.fromtimestamp(token['exp'], tz=tz)
        
        TokenBlocklist.add_token_to_blacklist(current_jti, current_type, user_id, current_expires_at)
        
        return jsonify({'message': 'You have been logged out from all devices.'}), 200
    except Exception as e:
        return jsonify({'error': f'Logout all failed: {str(e)}'}), 500

@bp.route('/verify', methods=['GET'])
@jwt_required()
def verify_token():
    """Verify if current access token is valid"""
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        token = get_jwt()
        return jsonify({
            'valid': True,
            'user': user.to_dict(),
            'token_exp': token.get('exp'),
            'token_iat': token.get('iat')
        }), 200
    except Exception as e:
        return jsonify({'error': f'Token verification failed: {str(e)}'}), 500 
