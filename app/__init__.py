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


_worker_app = None


def get_worker_app():
    """The one Flask app for this process, for notification threads (LINE) and anything else that needs an app
    context outside a request. Use this, not create_app(), there.

    create_app() builds a new SQLAlchemy engine -- a new connection pool -- every time it is called, and nothing
    disposes the old one: called per alert it would leak a pool per alert until the database ran out of
    connection slots. The cached app is safe because it holds no per-camera state (the detection loops keep
    theirs on the Camera object of their own context).
    """
    global _worker_app
    if _worker_app is None:
        _worker_app = create_app()
    return _worker_app


def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')
    db.init_app(app)
    jwt.init_app(app)
    celery.conf.update(app.config)
   
    # Registered BEFORE CORS(): Flask runs after_request hooks in reverse order, so this runs AFTER flask-cors has
    # added its headers and can take them off again. The live view is loaded as an <img>, which needs no CORS; the
    # app-wide wildcard would only let any site's script read the stream's bytes.
    @app.after_request
    def _no_cors_on_live_view(response):
        if request.endpoint == 'stream.stream_camera':
            for h in ('Access-Control-Allow-Origin', 'Access-Control-Expose-Headers',
                      'Access-Control-Allow-Credentials', 'Access-Control-Allow-Methods',
                      'Access-Control-Allow-Headers'):
                response.headers.pop(h, None)
        return response

    CORS(app, resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type", "Authorization"],
            "supports_credentials": False
        }
    })


    # Paths a request arriving over the public tunnel may reach: what LINE needs, nothing else.
    PUBLIC_EDGE_PREFIXES = ('/api/alert-images/', '/api/line/webhook')

    @app.before_request
    def _restrict_public_edge():
        """404 anything on the public hostname that LINE does not need.

        The public host is the one in PUBLIC_BASE_URL, so this only engages once a tunnel is configured. A request
        counts as public when EITHER its Host or its X-Forwarded-Host (cloudflared and similar proxies rewrite
        Host) is that host; looking at both means a header can only add the restriction, never remove it. The
        main defence is tools/line_test_proxy.py in front of the tunnel; this is the second layer for the day the
        tunnel points at the backend directly.
        """
        public_base = (app.config.get('PUBLIC_BASE_URL') or '').strip()
        if not public_base:
            return None
        public_host = public_base.split('//')[-1].split('/')[0].split(':')[0].lower()
        seen = [request.host or '']
        seen += (request.headers.get('X-Forwarded-Host') or '').split(',')
        if public_host not in {h.strip().split(':')[0].lower() for h in seen}:
            return None  # local/LAN request -- untouched
        if request.path.startswith(PUBLIC_EDGE_PREFIXES):
            return None
        from flask import abort
        abort(404)

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
            # Fails closed, like TokenBlocklist.is_jti_blacklisted itself.
            print(f"Error checking token blacklist, treating token as revoked: {e}")
            return True


    from .models import user, camera, detection_log, system_log, notification_history, telegram_settings, token_blocklist, thai_frat_assessment, line_settings, line_target
   
    with app.app_context():
        try:
            db.create_all()
            from app.models.user import User, UserRole


            # create_all() never alters an existing table: add the columns models gained since (idempotent,
            # additive only, see app/db_migrate.py)
            from app.db_migrate import ensure_columns
            ensure_columns(db)


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

