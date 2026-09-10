from flask import Blueprint, request, jsonify
from app import db
from app.models.telegram_settings import TelegramSettings
from flask_jwt_extended import jwt_required, get_jwt_identity

bp = Blueprint('telegram', __name__, url_prefix='/api/telegram')

@bp.route('/settings', methods=['GET'])
@jwt_required()
def get_telegram_settings():
    try:
        user_id = int(get_jwt_identity())
        settings = TelegramSettings.get_settings(user_id)
        return jsonify({
            'success': True,
            'data': settings.to_dict()
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get Telegram settings: {str(e)}'
        }), 500

@bp.route('/settings', methods=['POST'])
@jwt_required()
def update_telegram_settings():
    try:
        user_id = int(get_jwt_identity())
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400
        
        bot_token = data.get('bot_token')
        chat_id = data.get('chat_id')
        
        if bot_token is None and chat_id is None:
            return jsonify({
                'success': False,
                'error': 'At least one of bot_token or chat_id must be provided'
            }), 400
        
        if bot_token is not None and bot_token.strip() == '':
            return jsonify({
                'success': False,
                'error': 'Bot token cannot be empty'
            }), 400
        
        if chat_id is not None and chat_id.strip() == '':
            return jsonify({
                'success': False,
                'error': 'Chat ID cannot be empty'
            }), 400
        
        settings = TelegramSettings.update_settings(
            user_id=user_id,
            bot_token=bot_token.strip() if bot_token is not None else None,
            chat_id=chat_id.strip() if chat_id is not None else None
        )
        
        return jsonify({
            'success': True,
            'message': 'Telegram settings updated successfully',
            'data': settings.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to update Telegram settings: {str(e)}'
        }), 500

@bp.route('/test', methods=['POST'])
@jwt_required()
def test_telegram_settings():
    try:
        import requests
        user_id = int(get_jwt_identity())
        
        settings = TelegramSettings.get_settings(user_id)
        
        if not settings.bot_token or not settings.chat_id:
            return jsonify({
                'success': False,
                'error': 'Both bot_token and chat_id must be configured before testing'
            }), 400
        
        text = "🤖 *Test Message*\n\nThis is a test message from the Elderly Surveillance System.\nIf you receive this message, your Telegram settings are working correctly!"
        url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
        data = {
            'chat_id': settings.chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            return jsonify({
                'success': True,
                'message': 'Test message sent successfully!'
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to send test message. Telegram API responded with: {response.text}'
            }), 400
            
    except requests.exceptions.RequestException as e:
        return jsonify({
            'success': False,
            'error': f'Network error while testing Telegram settings: {str(e)}'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to test Telegram settings: {str(e)}'
        }), 500
