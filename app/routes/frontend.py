"""Frontend blueprint: serves the trap-management web UI.

Only registered when ``ENABLE_FRONTEND`` is true (see ``create_app``); when
disabled the route is absent and requests to ``/traps`` return 404.
"""
from flask import Blueprint, render_template

frontend_bp = Blueprint("frontend", __name__)


@frontend_bp.route("/traps", methods=["GET"])
def traps_page():
    return render_template("traps.html")


@frontend_bp.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")
