"""Shared storage helpers for deployment action pictures."""
import os

from flask import current_app


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif"}


def upload_dir():
    return os.path.join(current_app.config["DATA_DIR"], "uploads")


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def stored_file_path(stored_filename):
    """Resolve a generated filename without allowing path traversal."""
    stored_name = os.path.basename(stored_filename or "")
    if not stored_name or stored_name != stored_filename:
        return None

    candidates = [
        os.path.join(upload_dir(), stored_name),
        os.path.join(current_app.static_folder, "uploads", stored_name),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def remove_stored_file(stored_filename):
    path = stored_file_path(stored_filename)
    if path is not None:
        os.remove(path)
