import os
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from celery import Celery
from dotenv import load_dotenv
from flask_cors import CORS


from sqlalchemy import text
from sqlalchemy import inspect


load_dotenv()


db = SQLAlchemy()
jwt = JWTManager()
celery = Celery(__name__)


import app.services.camera_manager


def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')
    db.init_app(app)
    jwt.init_app(app)
    celery.conf.update(app.config)
   
    CORS(app, resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type", "Authorization"],
            "supports_credentials": False
        }
    })


    @app.before_request
    def _handle_options_requests():
        if request.method == 'OPTIONS':
            response = app.make_default_options_response()
            return response


    # Add static file serving for videos
    from flask import send_from_directory
   
    @app.route('/videos/<filename>')
    def serve_video(filename):
        video_dir = '/app/videos'  # Use absolute path to videos folder
        if not os.path.exists(video_dir):
            os.makedirs(video_dir)
        return send_from_directory(video_dir, filename)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        try:
            from app.models.token_blocklist import TokenBlocklist
            jti = jwt_payload['jti']
            return TokenBlocklist.is_jti_blacklisted(jti)
        except Exception as e:
            print(f"Error checking token blacklist: {e}")
            return False


    from .models import user, camera, detection_log, system_log, notification_history, telegram_settings, token_blocklist, thai_frat_assessment
   
    with app.app_context():
        try:
            db.create_all()
            from app.models.user import User, UserRole


            # Automatically add telegram_chat_id column if it is missing in existing DB
            inspector = inspect(db.engine)
            if 'users' in inspector.get_table_names() and 'telegram_chat_id' not in [c['name'] for c in inspector.get_columns('users')]:
                try:
                    db.session.execute(text('ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(255)'))
                    db.session.commit()
                    print('Added missing column telegram_chat_id to users table')
                except Exception as e:
                    db.session.rollback()
                    print(f'Could not add telegram_chat_id column automatically: {e}')


            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', role=UserRole.ADMIN)
                admin.set_password('admin123')
                db.session.add(admin)
                print("Created admin user: username='admin', password='admin123', role='admin'")
           
            if not User.query.filter_by(username='testuser').first():
                test_user = User(username='testuser', role=UserRole.USER)
                test_user.set_password('user123')
                db.session.add(test_user)
                print("Created test user: username='testuser', password='user123', role='user'")
           
            db.session.commit()
            print("Database tables created successfully!")
        except Exception as e:
            print(f"Error creating tables: {e}")
            db.session.rollback()


    from .routes import register_blueprints
    register_blueprints(app)


    return app

