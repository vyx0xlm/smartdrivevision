"""Shared paths for SQLite DB and uploads (local dev vs Render persistent disk)."""

import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """Persistent storage root. On Render, set DATA_DIR=/var/data."""
    explicit = (os.environ.get('DATA_DIR') or '').strip()
    if explicit:
        return explicit
    db_path = get_database_path()
    return os.path.dirname(db_path)


def get_database_path() -> str:
    """SQLite file path. On Render, set DATABASE_PATH=/var/data/smartdrive.db."""
    explicit = (os.environ.get('DATABASE_PATH') or '').strip()
    if explicit:
        return explicit
    return os.path.join(_APP_DIR, 'smartdrive.db')


def get_profile_upload_dir() -> str:
    """Profile photo storage. Uses DATA_DIR when set so uploads survive redeploys."""
    explicit = (os.environ.get('PROFILE_UPLOAD_DIR') or '').strip()
    if explicit:
        return explicit
    data_dir = get_data_dir()
    if os.path.normpath(data_dir) != os.path.normpath(_APP_DIR):
        return os.path.join(data_dir, 'uploads', 'profiles')
    return os.path.join(_APP_DIR, 'static', 'uploads', 'profiles')


def ensure_data_dirs() -> None:
    os.makedirs(os.path.dirname(get_database_path()), exist_ok=True)
    os.makedirs(get_profile_upload_dir(), exist_ok=True)
