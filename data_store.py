"""
Data access layer — SQLite (local) or Firestore (Firebase live).
Set USE_FIREBASE=1 and GOOGLE_APPLICATION_CREDENTIALS for cloud mode.
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from firebase_service import firebase_enabled, init_firebase

DATABASE = os.path.join(os.path.dirname(__file__), 'smartdrive.db')
LOCAL_TIME_OFFSET = '+8 hours'


def normalize_phone(phone: str) -> str:
    """Digits only for duplicate comparison (+60… vs 60…)."""
    return re.sub(r'\D', '', (phone or '').strip())


# ── SQLite backend ────────────────────────────────────────────────────────────

def _sqlite_conn():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_init_db():
    conn = _sqlite_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            onboarding_done INTEGER DEFAULT 0,
            firebase_uid TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_code TEXT UNIQUE,
            user_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            vehicle_info TEXT,
            device_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS emergency_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            relationship TEXT,
            is_primary INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers (id)
        );
        CREATE TABLE IF NOT EXISTS alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            driver_id INTEGER,
            alert_type TEXT DEFAULT 'SMS',
            alert_recipients TEXT,
            message TEXT NOT NULL,
            source TEXT DEFAULT 'iot',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (driver_id) REFERENCES drivers (id)
        );
    ''')
    cols = {r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()}
    if 'onboarding_done' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN onboarding_done INTEGER DEFAULT 0')
    if 'firebase_uid' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN firebase_uid TEXT')
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_emergency_primary_per_driver '
        'ON emergency_contacts(driver_id) WHERE is_primary = 1'
    )
    conn.commit()
    conn.close()


def sqlite_user_by_id(uid):
    conn = _sqlite_conn()
    row = conn.execute(
        'SELECT id, email, full_name, phone, onboarding_done, firebase_uid FROM users WHERE id = ?',
        (int(uid),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def sqlite_user_by_email(email):
    conn = _sqlite_conn()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def sqlite_user_by_firebase_uid(fb_uid):
    conn = _sqlite_conn()
    row = conn.execute('SELECT * FROM users WHERE firebase_uid = ?', (fb_uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def sqlite_create_user(email, password, full_name, phone=None, firebase_uid=None):
    conn = _sqlite_conn()
    try:
        conn.execute(
            'INSERT INTO users (email, password_hash, full_name, phone, firebase_uid) VALUES (?, ?, ?, ?, ?)',
            (email.lower(), generate_password_hash(password) if password else '', full_name, phone, firebase_uid),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        return None


def sqlite_upsert_firebase_user(fb_uid, email, full_name, phone=None):
    conn = _sqlite_conn()
    row = conn.execute('SELECT * FROM users WHERE firebase_uid = ? OR email = ?', (fb_uid, email.lower())).fetchone()
    if row:
        conn.execute(
            'UPDATE users SET firebase_uid=?, full_name=?, phone=COALESCE(?, phone) WHERE id=?',
            (fb_uid, full_name, phone, row['id']),
        )
        conn.commit()
        uid = row['id']
    else:
        conn.execute(
            'INSERT INTO users (email, password_hash, full_name, phone, firebase_uid) VALUES (?, ?, ?, ?, ?)',
            (email.lower(), '', full_name, phone, fb_uid),
        )
        conn.commit()
        uid = conn.execute('SELECT id FROM users WHERE firebase_uid = ?', (fb_uid,)).fetchone()['id']
    conn.close()
    return sqlite_user_by_id(uid)


def sqlite_set_onboarding_done(uid):
    conn = _sqlite_conn()
    conn.execute('UPDATE users SET onboarding_done = 1 WHERE id = ?', (int(uid),))
    conn.commit()
    conn.close()


def sqlite_emergency_phone_taken(driver_id, phone, exclude_contact_id=None):
    norm = normalize_phone(phone)
    if not norm:
        return False
    conn = _sqlite_conn()
    rows = conn.execute(
        'SELECT id, phone FROM emergency_contacts WHERE driver_id = ?',
        (int(driver_id),),
    ).fetchall()
    conn.close()
    for r in rows:
        if exclude_contact_id and int(r['id']) == int(exclude_contact_id):
            continue
        if normalize_phone(r['phone']) == norm:
            return True
    return False


def sqlite_next_driver_code(conn):
    rows = conn.execute("SELECT driver_code FROM drivers WHERE driver_code LIKE 'DR%'").fetchall()
    max_num = 0
    for row in rows:
        code = (row['driver_code'] or '').strip()
        if len(code) >= 5 and code[2:].isdigit():
            max_num = max(max_num, int(code[2:]))
    return f'DR{max_num + 1:03d}'


# ── Firestore backend ─────────────────────────────────────────────────────────

def _fs():
    return init_firebase()


def fs_user_doc(uid):
    return _fs().collection('users').document(str(uid))


def fs_upsert_firebase_user(fb_uid, email, full_name, phone=None):
    db = _fs()
    ref = db.collection('users').document(fb_uid)
    snap = ref.get()
    data = {
        'email': email.lower(),
        'full_name': full_name,
        'phone': phone,
        'firebase_uid': fb_uid,
        'updated_at': datetime.utcnow().isoformat(),
    }
    if not snap.exists:
        data['onboarding_done'] = False
        data['created_at'] = datetime.utcnow().isoformat()
        data['driver_seq'] = 0
    ref.set(data, merge=True)
    return fs_user_by_id(fb_uid)


def fs_user_by_id(uid):
    snap = fs_user_doc(uid).get()
    if not snap.exists:
        return None
    d = snap.to_dict()
    d['id'] = uid
    return d


def fs_set_onboarding_done(uid):
    fs_user_doc(uid).update({'onboarding_done': True})


def fs_emergency_phone_taken(driver_id, phone, exclude_contact_id=None):
    norm = normalize_phone(phone)
    if not norm:
        return False
    for doc in _fs().collection('emergency_contacts').where('driver_id', '==', str(driver_id)).stream():
        if exclude_contact_id and doc.id == str(exclude_contact_id):
            continue
        if normalize_phone(doc.to_dict().get('phone', '')) == norm:
            return True
    return False


def fs_next_driver_code(user_id):
    ref = fs_user_doc(user_id)
    snap = ref.get()
    seq = (snap.to_dict() or {}).get('driver_seq', 0) + 1
    ref.update({'driver_seq': seq})
    return f'DR{seq:03d}'


def use_firestore():
    """Firestore for app data — separate from Firebase Auth (Google sign-in)."""
    flag = os.environ.get('USE_FIRESTORE', os.environ.get('USE_FIREBASE', ''))
    if str(flag).lower() not in ('1', 'true', 'yes'):
        return False
    try:
        return init_firebase() is not None
    except Exception:
        return False


# ── Unified API (pick backend) ───────────────────────────────────────────────

def init_db():
    """Always ensure SQLite exists (used for auth + local data). Optionally init Firestore."""
    sqlite_init_db()
    if use_firestore():
        try:
            init_firebase()
        except Exception as exc:
            print(f'[Firestore] Init skipped: {exc}')


def user_by_id(uid):
    if use_firestore():
        return fs_user_by_id(str(uid))
    return sqlite_user_by_id(uid)


def user_by_email(email):
    if use_firestore():
        db = _fs()
        for doc in db.collection('users').where('email', '==', email.lower()).limit(1).stream():
            d = doc.to_dict()
            d['id'] = doc.id
            return d
        return None
    return sqlite_user_by_email(email)


def upsert_firebase_user(fb_uid, email, full_name, phone=None):
    """Google/email sign-in users are stored in SQLite (reliable). Firestore optional later."""
    try:
        return sqlite_upsert_firebase_user(fb_uid, email, full_name, phone)
    except Exception as exc:
        print(f'[Auth] SQLite upsert failed: {exc}')
        return None


def set_onboarding_done(uid):
    if use_firestore():
        fs_set_onboarding_done(str(uid))
    else:
        sqlite_set_onboarding_done(uid)


def emergency_phone_taken(driver_id, phone, exclude_contact_id=None):
    if use_firestore():
        return fs_emergency_phone_taken(driver_id, phone, exclude_contact_id)
    return sqlite_emergency_phone_taken(driver_id, phone, exclude_contact_id)
