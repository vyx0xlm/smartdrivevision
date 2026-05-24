"""Firebase Admin SDK — Auth token verification and Firestore client."""

import json
import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_firebase_app = None
_db = None


def _default_web_config_path() -> str:
    return os.path.join(_APP_DIR, 'firebase_web_config.json')


def _service_account_dict() -> dict | None:
    raw = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    if path and not os.path.isabs(path):
        path = os.path.join(_APP_DIR, path)
    if not path or not os.path.isfile(path):
        path = os.path.join(_APP_DIR, 'serviceAccountKey.json')
    if path and os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None


def firebase_enabled() -> bool:
    """True when Admin SDK credentials are available (Auth verify + optional Firestore)."""
    if _service_account_dict():
        return True
    return os.environ.get('USE_FIREBASE', '').lower() in ('1', 'true', 'yes')


def get_firebase_web_config() -> dict | None:
    """Public Firebase web config for client SDK (from env JSON or file)."""
    raw = os.environ.get('FIREBASE_WEB_CONFIG', '').strip()
    if not raw:
        path = os.environ.get('FIREBASE_WEB_CONFIG_PATH', '')
        if path and not os.path.isabs(path):
            path = os.path.join(_APP_DIR, path)
        if not path or not os.path.isfile(path):
            path = _default_web_config_path()
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                raw = f.read()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _ensure_firebase_app():
    global _firebase_app
    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return
    sa = _service_account_dict()
    if not sa:
        raise RuntimeError('Firebase service account not configured')
    _firebase_app = firebase_admin.initialize_app(credentials.Certificate(sa))


def init_firebase():
    global _firebase_app, _db
    if _db is not None:
        return _db
    if not firebase_enabled():
        return None
    from firebase_admin import firestore

    _ensure_firebase_app()
    _db = firestore.client()
    return _db


def verify_id_token(id_token: str) -> dict:
    from firebase_admin import auth
    _ensure_firebase_app()
    decoded = auth.verify_id_token(id_token)
    return {
        'uid': decoded['uid'],
        'email': (decoded.get('email') or '').lower(),
        'name': decoded.get('name') or decoded.get('display_name') or '',
    }


def send_password_reset_email(email: str) -> None:
    """Generate password-reset link (or use client SDK on web)."""
    from firebase_admin import auth
    _ensure_firebase_app()
    auth.generate_password_reset_link(email)


def delete_firebase_auth_user(fb_uid: str) -> bool:
    """Remove Firebase Auth user (Google/email). Returns False if skipped or failed."""
    if not fb_uid or not firebase_enabled():
        return False
    try:
        from firebase_admin import auth
        _ensure_firebase_app()
        auth.delete_user(fb_uid)
        return True
    except Exception:
        return False
