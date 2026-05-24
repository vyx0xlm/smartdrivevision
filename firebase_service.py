"""Firebase Admin SDK — Auth token verification and Firestore client."""

import json
import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_firebase_app = None
_db = None


def _default_web_config_path() -> str:
    return os.path.join(_APP_DIR, 'firebase_web_config.json')


def firebase_enabled() -> bool:
    """True when Admin SDK credentials are available (Auth verify + optional Firestore)."""
    cred = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    if cred and not os.path.isabs(cred):
        cred = os.path.join(_APP_DIR, cred)
    if cred and os.path.isfile(cred):
        os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS', cred)
        return True
    default_sa = os.path.join(_APP_DIR, 'serviceAccountKey.json')
    if os.path.isfile(default_sa):
        os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS', default_sa)
        return True
    return os.environ.get('USE_FIREBASE', '').lower() in ('1', 'true', 'yes')


def get_firebase_web_config() -> dict | None:
    """Public Firebase web config for client SDK (from env JSON)."""
    raw = os.environ.get('FIREBASE_WEB_CONFIG', '')
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


def init_firebase():
    global _firebase_app, _db
    if _db is not None:
        return _db
    if not firebase_enabled():
        return None
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
        if cred_path and os.path.isfile(cred_path):
            cred = credentials.Certificate(cred_path)
        else:
            cred = credentials.ApplicationDefault()
        _firebase_app = firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _db


def verify_id_token(id_token: str) -> dict:
    from firebase_admin import auth
    init_firebase()
    decoded = auth.verify_id_token(id_token)
    return {
        'uid': decoded['uid'],
        'email': (decoded.get('email') or '').lower(),
        'name': decoded.get('name') or decoded.get('display_name') or '',
    }


def send_password_reset_email(email: str) -> None:
    """Generate password-reset link (or use client SDK on web)."""
    from firebase_admin import auth
    init_firebase()
    auth.generate_password_reset_link(email)
