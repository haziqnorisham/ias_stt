"""Flask application factory and logging setup."""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify

from app.config import Config


def _configure_logging(app: Flask) -> None:
    os.makedirs(app.config["LOG_DIR"], exist_ok=True)

    log_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(module)s:%(lineno)d - %(message)s"
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


def create_app(config_class: type = Config) -> Flask:
    """Application factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    _configure_logging(app)
    _register_error_handlers(app)

    from app.auth import init_auth

    init_auth(app)

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)

    from app.models.database import db

    db.init_app(app)
    with app.app_context():
        from app.models.deployment import Deployment  # noqa: F401
        from app.models.deployment_location import DeploymentLocation  # noqa: F401
        from app.models.trap import Trap  # noqa: F401  (register model)

        db.create_all()

    from app.routes.api import api_bp
    from app.routes.traps import traps_bp
    from app.routes.deployments import deployments_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(traps_bp)
    app.register_blueprint(deployments_bp)

    if app.config["ENABLE_FRONTEND"]:
        from app.routes.frontend import frontend_bp

        app.register_blueprint(frontend_bp)
        app.logger.info("Frontend UI enabled at /traps")
    else:
        app.logger.info("Frontend UI disabled (ENABLE_FRONTEND=false)")

    app.logger.info("Flask application initialized")

    from app.services.mqtt_service import init_mqtt

    init_mqtt(app)

    return app
