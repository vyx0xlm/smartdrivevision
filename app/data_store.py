"""
Data access layer — SQLite/PostgreSQL (via database.py) or Firestore (optional).
Set DATABASE_URL for Render Postgres. Set USE_FIREBASE=1 for Firestore (legacy).
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from firebase_service import firebase_enabled, init_firebase
from database import get_db, init_schema, use_postgres


def normalize_phone(phone: str) -> str:
    """Digits only for duplicate comparison (+60… vs 60…)."""
    return re.sub(r'\D', '', (phone or '').strip())


# ── SQLite / PostgreSQL backend ───────────────────────────────────────────────

def _sql_conn():
    return get_db()


def sqlite_init_db():
    init_schema()


def sqlite_user_by_id(uid):
    conn = _sql_conn()
    row = conn.execute(
        'SELECT id, email, full_name, phone, onboarding_done, firebase_uid FROM users WHERE id = ?',
        (int(uid),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def sqlite_user_by_email(email):
    conn = _sql_conn()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def sqlite_user_by_firebase_uid(fb_uid):
    conn = _sql_conn()
    row = conn.execute('SELECT * FROM users WHERE firebase_uid = ?', (fb_uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def sqlite_create_user(email, password, full_name, phone=None, firebase_uid=None):
    conn = _sql_conn()
    try:
        conn.execute(
            'INSERT INTO users (email, password_hash, full_name, phone, firebase_uid) VALUES (?, ?, ?, ?, ?)',
            (email.lower(), generate_password_hash(password) if password else '', full_name, phone, firebase_uid),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()
        conn.close()
        return dict(row)
    except Exception as exc:
        try:
            conn._conn.rollback()
        except Exception:
            pass
        conn.close()
        if isinstance(exc, sqlite3.IntegrityError):
            return None
        if use_postgres():
            import psycopg2

            if isinstance(exc, psycopg2.IntegrityError):
                return None
        raise


def sqlite_upsert_firebase_user(fb_uid, email, full_name, phone=None):
    conn = _sql_conn()
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
    conn = _sql_conn()
    conn.execute('UPDATE users SET onboarding_done = 1 WHERE id = ?', (int(uid),))
    conn.commit()
    conn.close()


def sqlite_emergency_phone_taken(driver_id, phone, exclude_contact_id=None):
    norm = normalize_phone(phone)
    if not norm:
        return False
    conn = _sql_conn()
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
    """Ensure SQL schema (SQLite or Postgres) and optionally init Firestore."""
    if not use_firestore():
        init_schema()
    elif use_firestore():
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
