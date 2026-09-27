"""Flask application factory and logging setup."""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.time_utils import AppTimezoneFormatter


def _configure_logging(app: Flask) -> None:
    os.makedirs(app.config["LOG_DIR"], exist_ok=True)

    log_format = AppTimezoneFormatter(
        "%(asctime)s [%(levelname)s] %(name)s %(module)s:%(lineno)d - %(message)s",
        timezone_name=app.config["APP_TIMEZONE"],
    )
    level = getattr(logging, app.config["LOG_LEVEL"].upper(), logging.DEBUG)

    file_handler = RotatingFileHandler(
        os.path.join(app.config["LOG_DIR"], "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(level)

    for handler in app.logger.handlers:
        handler.close()
    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(level)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not Found"}), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Internal server error")
        return jsonify({"error": "Internal Server Error"}), 500

    @app.before_request
    def block_public_upload_paths():
        # Uploaded images are served through an authenticated deployment route.
        if request.path.startswith("/static/uploads/"):
            return jsonify({"error": "Not Found"}), 404


def create_app(config_class: type = Config) -> Flask:
    """Application factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    trusted_proxy_hops = app.config.get("TRUSTED_PROXY_HOPS", 0)
    if trusted_proxy_hops < 0 or trusted_proxy_hops > 5:
        raise RuntimeError("TRUSTED_PROXY_HOPS must be between 0 and 5")
    if trusted_proxy_hops:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_proto=trusted_proxy_hops,
        )
    CORS(
        app,
        origins="*",
        send_wildcard=True,
        allow_headers=["Accept", "Content-Type", "Authorization"],
        supports_credentials=False,
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    _configure_logging(app)
    _register_error_handlers(app)

    from app.auth import init_auth

    init_auth(app)

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)

    from app.models.database import db

    db.init_app(app)
    with app.app_context():
        from app.models.database import set_engine

        set_engine(db.engine)

        from app.models.deployment import Deployment  # noqa: F401
        from app.models.deployment_action import DeploymentAction  # noqa: F401
        from app.models.deployment_action_type import (  # noqa: F401
            DeploymentActionType,
            seed_default_action_types,
        )
        from app.models.deployment_location import DeploymentLocation  # noqa: F401
        from app.models.smart_trap_tracker import SmartTrapTracker  # noqa: F401
        from app.models.tracker_uplink import TrackerUplink  # noqa: F401
        from app.models.trap import Trap  # noqa: F401  (register model)
        from app.models.server_configuration import server_configuration  # noqa: F401  (register model)
        from app.models.user import User  # noqa: F401  (register model)
        from app.models.notification import (  # noqa: F401  (register models)
            Notification,
            NotificationUserState,
        )

        db.create_all()
        seed_default_action_types()
        from app.schema_migrations import upgrade_schema

        upgrade_schema(db.engine)

    from app.routes.api import api_bp
    from app.routes.auth import auth_bp
    from app.routes.traps import traps_bp
    from app.routes.users import ldap_users_bp, users_bp
    from app.routes.deployments import deployments_bp
    from app.routes.deployment_actions import deployment_actions_bp
    from app.routes.trackers import trackers_bp
    from app.routes.uplinks import uplinks_bp
    from app.routes.server_configuration import server_configuration_bp
    from app.routes.notifications import notifications_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(traps_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(ldap_users_bp)
    app.register_blueprint(deployments_bp)
    app.register_blueprint(deployment_actions_bp)
    app.register_blueprint(trackers_bp)
    app.register_blueprint(uplinks_bp)
    app.register_blueprint(server_configuration_bp)
    app.register_blueprint(notifications_bp)

    if app.config["ENABLE_FRONTEND"]:
        from app.routes.frontend import frontend_bp

        app.register_blueprint(frontend_bp)
        app.logger.info("Frontend UI enabled at /traps")
    else:
        app.logger.info("Frontend UI disabled (ENABLE_FRONTEND=false)")

    app.logger.info("Flask application initialized")

    from app.cli import register_cli

    register_cli(app)

    from app.services.mqtt_service import init_mqtt

    init_mqtt(app)

    return app
