def register_blueprints(app):
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)
    from .cameras import bp as cameras_bp
    app.register_blueprint(cameras_bp)
    from .admin import bp as admin_bp
    app.register_blueprint(admin_bp)
    from .logs import bp as logs_bp
    app.register_blueprint(logs_bp)
    from .system_logs import bp as system_logs_bp
    app.register_blueprint(system_logs_bp)
    from .health import bp as health_bp
    app.register_blueprint(health_bp)
    from .telegram import bp as telegram_bp
    app.register_blueprint(telegram_bp)
    from .thai_frat import bp as thai_frat_bp
    app.register_blueprint(thai_frat_bp)
    from .alerts import bp as alerts_bp
    app.register_blueprint(alerts_bp)
    from .stream import bp as stream_bp
    app.register_blueprint(stream_bp) 