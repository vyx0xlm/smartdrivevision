"""
SmartDrive - Driver Drowsiness Detection App
Auth, profile, dedicated emergency contacts, dashboard, alert log, IoT API.
"""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    flash,
    session,
)
from flask_cors import CORS
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_user,
    logout_user,
    login_required,
)
from werkzeug.security import generate_password_hash, check_password_hash

from data_store import (
    init_db as datastore_init,
    set_onboarding_done,
    emergency_phone_taken,
    upsert_firebase_user,
    use_firestore,
)
from firebase_service import firebase_enabled, get_firebase_web_config, verify_id_token

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
CORS(app)
LOCAL_TIME_OFFSET = '+8 hours'  # Malaysia time (UTC+8)

if os.environ.get('BEHIND_PROXY', '').strip() in ('1', 'true', 'yes'):
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to access this page.'

DATABASE = os.path.join(os.path.dirname(__file__), 'smartdrive.db')
PROFILE_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'profiles')
ALLOWED_PROFILE_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


@app.context_processor
def inject_globals():
    return {'firebase_config': get_firebase_web_config()}


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn, name):
    return {r[1] for r in conn.execute(f'PRAGMA table_info({name})').fetchall()}


def init_db():
    """Create and migrate database (SQLite or Firestore)."""
    datastore_init()
    if use_firestore():
        return
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
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

    cols = _table_columns(conn, 'drivers')
    if 'user_id' not in cols:
        conn.execute('ALTER TABLE drivers ADD COLUMN user_id INTEGER REFERENCES users (id)')
    if 'driver_code' not in cols:
        conn.execute('ALTER TABLE drivers ADD COLUMN driver_code TEXT')
        # Backfill legacy drivers with DRxxx codes.
        rows = conn.execute('SELECT id FROM drivers WHERE driver_code IS NULL OR TRIM(driver_code) = "" ORDER BY id').fetchall()
        for idx, row in enumerate(rows, start=1):
            conn.execute(
                'UPDATE drivers SET driver_code = ? WHERE id = ?',
                (f'DR{idx:03d}', row['id']),
            )
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_drivers_driver_code ON drivers(driver_code)')
    user_cols = _table_columns(conn, 'users')
    if 'onboarding_done' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN onboarding_done INTEGER DEFAULT 0')
    if 'firebase_uid' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN firebase_uid TEXT')
    if 'profile_picture' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN profile_picture TEXT')
    alert_cols = _table_columns(conn, 'alert_events')
    if 'alert_type' not in alert_cols:
        conn.execute("ALTER TABLE alert_events ADD COLUMN alert_type TEXT DEFAULT 'SMS'")
        conn.execute("UPDATE alert_events SET alert_type = 'SMS' WHERE alert_type IS NULL OR TRIM(alert_type) = ''")
    if 'alert_recipients' not in alert_cols:
        conn.execute("ALTER TABLE alert_events ADD COLUMN alert_recipients TEXT")
        conn.execute("UPDATE alert_events SET alert_recipients = '' WHERE alert_recipients IS NULL")
    # Ensure each driver can have at most one primary emergency contact.
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_emergency_primary_per_driver '
        'ON emergency_contacts(driver_id) WHERE is_primary = 1'
    )

    conn.commit()
    conn.close()
    os.makedirs(PROFILE_UPLOAD_DIR, exist_ok=True)


class User(UserMixin):
    def __init__(self, uid, email, full_name, phone=None, onboarding_done=False):
        self.id = uid
        self.email = email
        self.full_name = full_name
        self.phone = phone
        self.onboarding_done = bool(onboarding_done)


def row_user(row):
    if isinstance(row, dict):
        return User(
            row['id'], row['email'], row['full_name'], row.get('phone'),
            row.get('onboarding_done', False),
        )
    keys = row.keys()
    return User(
        row['id'], row['email'], row['full_name'], row['phone'],
        row['onboarding_done'] if 'onboarding_done' in keys else False,
    )


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute(
        'SELECT id, email, full_name, phone, onboarding_done FROM users WHERE id = ?',
        (int(user_id),),
    ).fetchone()
    conn.close()
    return row_user(row) if row else None


def get_driver_for_user(conn, driver_id, user_id):
    return conn.execute(
        'SELECT * FROM drivers WHERE id = ? AND user_id = ?', (driver_id, user_id)
    ).fetchone()


def next_driver_code(conn):
    """Generate next driver code like DR001, DR002, ..."""
    rows = conn.execute(
        "SELECT driver_code FROM drivers WHERE driver_code LIKE 'DR%'"
    ).fetchall()
    max_num = 0
    for row in rows:
        code = (row['driver_code'] or '').strip()
        if len(code) >= 5 and code[2:].isdigit():
            max_num = max(max_num, int(code[2:]))
    return f'DR{max_num + 1:03d}'


def ensure_driver_for_user(conn, user_id):
    """One driver record per account — used by IoT API and emergency contacts."""
    row = conn.execute(
        'SELECT * FROM drivers WHERE user_id = ? ORDER BY id LIMIT 1', (user_id,)
    ).fetchone()
    if row:
        return dict(row)
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return None
    driver_code = next_driver_code(conn)
    phone = (user['phone'] or '').strip() or 'N/A'
    conn.execute(
        'INSERT INTO drivers (driver_code, user_id, name, phone, email, vehicle_info, device_id) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            driver_code,
            user_id,
            user['full_name'],
            phone,
            user['email'],
            None,
            None,
        ),
    )
    conn.commit()
    row = conn.execute(
        'SELECT * FROM drivers WHERE user_id = ? ORDER BY id DESC LIMIT 1', (user_id,)
    ).fetchone()
    return dict(row) if row else None


def sync_driver_from_profile(conn, user_id, full_name, phone, email, vehicle_info):
    driver = ensure_driver_for_user(conn, user_id)
    conn.execute(
        'UPDATE drivers SET name=?, phone=?, email=?, vehicle_info=? '
        'WHERE id=? AND user_id=?',
        (
            full_name,
            phone or 'N/A',
            email,
            vehicle_info or None,
            driver['id'],
            user_id,
        ),
    )


def _profile_picture_abs_path(relative_path):
    if not relative_path:
        return None
    return os.path.join(os.path.dirname(__file__), 'static', relative_path.replace('/', os.sep))


def _delete_profile_picture_file(relative_path):
    path = _profile_picture_abs_path(relative_path)
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _save_profile_picture(user_id, file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_PROFILE_EXT:
        return 'invalid_type'
    filename = f'{user_id}_{uuid4().hex[:8]}.{ext}'
    os.makedirs(PROFILE_UPLOAD_DIR, exist_ok=True)
    path = os.path.join(PROFILE_UPLOAD_DIR, secure_filename(filename))
    file_storage.save(path)
    return f'uploads/profiles/{os.path.basename(path)}'


def _profile_context(conn, user_id):
    user = conn.execute(
        'SELECT id, email, full_name, phone, profile_picture, password_hash FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    driver = ensure_driver_for_user(conn, user_id)
    u = dict(user)
    u.pop('password_hash', None)
    return {
        'user': u,
        'driver': driver,
        'has_local_password': bool(user['password_hash']),
    }


def _format_alert_recipients(conn, driver_id, alert_type, payload_value):
    """Create recipients text for alert log with policy by alert type.

    - CALL: only primary emergency contact (fallback to first contact).
    - SMS: all emergency contacts.
    """
    def _parse_payload_list(value):
        parts = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    name = str(item.get('name') or '').strip()
                    phone = str(item.get('phone') or '').strip()
                    if name and phone:
                        parts.append(f'{name} ({phone})')
                    elif phone:
                        parts.append(phone)
                    elif name:
                        parts.append(name)
                elif item is not None:
                    text = str(item).strip()
                    if text:
                        parts.append(text)
        return parts

    # For SMS, allow explicit recipients payload when provided by device.
    if alert_type == 'SMS':
        payload_parts = _parse_payload_list(payload_value)
        if payload_parts:
            return '\n'.join(payload_parts)
        if isinstance(payload_value, str) and payload_value.strip():
            return payload_value.strip()

        rows = conn.execute(
            'SELECT name, phone FROM emergency_contacts WHERE driver_id = ? ORDER BY is_primary DESC, name',
            (driver_id,),
        ).fetchall()
        return '\n'.join([f"{r['name']} ({r['phone']})" for r in rows]) if rows else ''

    # For CALL, always enforce primary-only from database.
    primary = conn.execute(
        'SELECT name, phone FROM emergency_contacts WHERE driver_id = ? AND is_primary = 1 ORDER BY name LIMIT 1',
        (driver_id,),
    ).fetchone()
    if primary:
        return primary['name']

    # Fallback when no primary is set: first available contact.
    fallback = conn.execute(
        'SELECT name, phone FROM emergency_contacts WHERE driver_id = ? ORDER BY name LIMIT 1',
        (driver_id,),
    ).fetchone()
    if fallback:
        return f"{fallback['name']} ({fallback['phone']})"
    return ''


def _get_existing_primary(conn, driver_id, exclude_contact_id=None):
    if exclude_contact_id is None:
        return conn.execute(
            'SELECT id, name, phone FROM emergency_contacts WHERE driver_id = ? AND is_primary = 1 LIMIT 1',
            (driver_id,),
        ).fetchone()
    return conn.execute(
        'SELECT id, name, phone FROM emergency_contacts WHERE driver_id = ? AND is_primary = 1 AND id <> ? LIMIT 1',
        (driver_id, exclude_contact_id),
    ).fetchone()


# ============ Auth ============

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip() or None

        if not email or not password or not full_name:
            flash('Please fill in all required fields.', 'error')
            return render_template('signup.html', firebase_config=get_firebase_web_config())

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('signup.html', firebase_config=get_firebase_web_config())

        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO users (email, password_hash, full_name, phone) VALUES (?, ?, ?, ?)',
                (email, generate_password_hash(password), full_name, phone),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            ensure_driver_for_user(conn, row['id'])
            conn.close()
            login_user(row_user(row))
            flash('Account created. Welcome to SmartDrive.', 'success')
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('An account with this email already exists.', 'error')
            return render_template('signup.html', firebase_config=get_firebase_web_config())

    return render_template('signup.html', firebase_config=get_firebase_web_config())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        conn = get_db()
        row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if row and check_password_hash(row['password_hash'], password):
            login_user(row_user(row))
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html', firebase_config=get_firebase_web_config())


@app.route('/auth/firebase', methods=['POST'])
def auth_firebase():
    """Google sign-in: verify Firebase token and create Flask session."""
    data = request.get_json(silent=True) or {}
    id_token = data.get('idToken') or data.get('id_token')
    if not id_token:
        return jsonify({'ok': False, 'error': 'missing token'}), 400
    if not firebase_enabled():
        return jsonify({
            'ok': False,
            'error': 'Add serviceAccountKey.json to the app folder (Firebase Console → Service accounts).',
        }), 503
    try:
        info = verify_id_token(id_token)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 401
    row = upsert_firebase_user(
        info['uid'],
        info['email'] or f"{info['uid']}@firebase.local",
        info['name'] or 'SmartDrive User',
    )
    if not row:
        return jsonify({'ok': False, 'error': 'could not save user'}), 500
    conn = get_db()
    ensure_driver_for_user(conn, row['id'])
    conn.close()
    login_user(row_user(row))
    return jsonify({'ok': True, 'redirect': url_for('dashboard')})


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('profile'))
    return render_template('forgot_password.html')


@app.route('/onboarding/complete', methods=['POST'])
@login_required
def onboarding_complete():
    set_onboarding_done(current_user.id)
    current_user.onboarding_done = True
    return jsonify({'ok': True})


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been signed out.', 'success')
    return redirect(url_for('login'))


# ============ Dashboard ============

@app.route('/')
def root():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    uid = current_user.id
    ensure_driver_for_user(conn, uid)
    contacts = conn.execute(
        '''SELECT COUNT(e.id) AS c FROM emergency_contacts e
           JOIN drivers d ON e.driver_id = d.id WHERE d.user_id = ?''',
        (uid,),
    ).fetchone()['c']
    since = (datetime.utcnow() - timedelta(days=30)).isoformat()
    alerts = conn.execute(
        'SELECT COUNT(*) AS c FROM alert_events WHERE user_id = ? AND created_at >= ?',
        (uid, since),
    ).fetchone()['c']
    recent = conn.execute(
        '''SELECT a.*, datetime(a.created_at, ?) AS created_at_local, dr.name AS driver_name FROM alert_events a
           LEFT JOIN drivers dr ON a.driver_id = dr.id
           WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT 5''',
        (LOCAL_TIME_OFFSET, uid),
    ).fetchall()
    onboarding = conn.execute(
        'SELECT onboarding_done FROM users WHERE id = ?', (uid,)
    ).fetchone()
    conn.close()
    show_onboarding = not bool(onboarding and onboarding['onboarding_done'])
    return render_template(
        'dashboard.html',
        stats={'contacts': contacts, 'alerts_month': alerts},
        recent_alerts=[dict(r) for r in recent],
        show_onboarding=show_onboarding,
    )


@app.route('/drivers')
@app.route('/driver/register', methods=['GET', 'POST'])
@app.route('/driver/<int:driver_id>')
@app.route('/driver/<int:driver_id>/edit', methods=['GET', 'POST'])
@app.route('/driver/<int:driver_id>/delete', methods=['POST'])
@login_required
def drivers_removed_redirect(**kwargs):
    """Legacy driver pages — profile is now the single driver record."""
    return redirect(url_for('profile'))


# ============ Emergency contacts ============

@app.route('/emergency-contacts')
@login_required
def emergency_contacts_page():
    conn = get_db()
    ensure_driver_for_user(conn, current_user.id)
    rows = conn.execute(
        '''SELECT e.* FROM emergency_contacts e
           JOIN drivers d ON e.driver_id = d.id
           WHERE d.user_id = ?
           ORDER BY e.is_primary DESC, e.name''',
        (current_user.id,),
    ).fetchall()
    conn.close()
    return render_template('emergency_contacts.html', contacts=[dict(r) for r in rows])


@app.route('/emergency-contacts/add', methods=['GET', 'POST'])
@login_required
def emergency_contact_add():
    conn = get_db()
    driver = ensure_driver_for_user(conn, current_user.id)
    driver_id = driver['id']

    if request.method == 'POST':
        data = request.form
        phone = data.get('phone', '').strip()
        if emergency_phone_taken(driver_id, phone):
            flash('This phone number is already in your emergency contacts.', 'error')
            conn.close()
            return render_template(
                'emergency_contact_form.html',
                mode='add',
                contact=None,
                form_data=dict(data),
                replace_required=False,
                existing_primary=None,
            )
        is_primary = 1 if data.get('is_primary') == 'on' else 0
        confirm_replace_primary = data.get('confirm_replace_primary') == 'on'
        existing_primary = _get_existing_primary(conn, driver_id) if is_primary else None
        if existing_primary and not confirm_replace_primary:
            warning = (
                f"Primary contact already exists: {existing_primary['name']} ({existing_primary['phone']}). "
                "Tick confirmation to replace or cancel."
            )
            flash(warning, 'error')
            conn.close()
            return render_template(
                'emergency_contact_form.html',
                mode='add',
                contact=None,
                form_data=dict(data),
                replace_required=True,
                existing_primary=dict(existing_primary),
            )
        if is_primary:
            conn.execute(
                'UPDATE emergency_contacts SET is_primary = 0 WHERE driver_id = ?',
                (driver_id,),
            )
        conn.execute(
            'INSERT INTO emergency_contacts (driver_id, name, phone, relationship, is_primary) '
            'VALUES (?, ?, ?, ?, ?)',
            (
                driver_id,
                data.get('name', '').strip(),
                phone,
                data.get('relationship', '').strip() or None,
                is_primary,
            ),
        )
        conn.commit()
        conn.close()
        flash('Emergency contact added.', 'success')
        return redirect(url_for('emergency_contacts_page'))

    conn.close()
    return render_template(
        'emergency_contact_form.html',
        mode='add',
        contact=None,
        form_data=None,
        replace_required=False,
        existing_primary=None,
    )


@app.route('/emergency-contacts/<int:contact_id>/edit', methods=['GET', 'POST'])
@login_required
def emergency_contact_edit(contact_id):
    conn = get_db()
    row = conn.execute(
        '''SELECT e.* FROM emergency_contacts e
           JOIN drivers d ON e.driver_id = d.id
           WHERE e.id = ? AND d.user_id = ?''',
        (contact_id, current_user.id),
    ).fetchone()
    if not row:
        conn.close()
        return 'Contact not found', 404
    contact = dict(row)
    driver_id = contact['driver_id']

    if request.method == 'POST':
        data = request.form
        phone = data.get('phone', '').strip()
        if emergency_phone_taken(driver_id, phone, exclude_contact_id=contact_id):
            flash('This phone number is already in your emergency contacts.', 'error')
            conn.close()
            return render_template(
                'emergency_contact_form.html',
                mode='edit',
                contact=contact,
                form_data=dict(data),
                replace_required=False,
                existing_primary=None,
            )
        is_primary = 1 if data.get('is_primary') == 'on' else 0
        confirm_replace_primary = data.get('confirm_replace_primary') == 'on'
        existing_primary = _get_existing_primary(conn, driver_id, contact_id) if is_primary else None
        if existing_primary and not confirm_replace_primary:
            flash(
                f"Primary contact already exists: {existing_primary['name']} ({existing_primary['phone']}). "
                "Tick confirmation to replace or cancel.",
                'error',
            )
            conn.close()
            return render_template(
                'emergency_contact_form.html',
                mode='edit',
                contact=contact,
                form_data=dict(data),
                replace_required=True,
                existing_primary=dict(existing_primary),
            )
        if is_primary:
            conn.execute(
                'UPDATE emergency_contacts SET is_primary = 0 WHERE driver_id = ? AND id <> ?',
                (driver_id, contact_id),
            )
        conn.execute(
            '''UPDATE emergency_contacts SET name=?, phone=?, relationship=?, is_primary=? WHERE id=?''',
            (
                data.get('name', '').strip(),
                phone,
                data.get('relationship', '').strip() or None,
                is_primary,
                contact_id,
            ),
        )
        conn.commit()
        conn.close()
        flash('Emergency contact updated.', 'success')
        return redirect(url_for('emergency_contacts_page'))

    conn.close()
    return render_template(
        'emergency_contact_form.html',
        mode='edit',
        contact=contact,
        form_data=None,
        replace_required=False,
        existing_primary=None,
    )


@app.route('/emergency-contacts/<int:contact_id>/delete', methods=['POST'])
@login_required
def emergency_contact_delete(contact_id):
    conn = get_db()
    row = conn.execute(
        '''SELECT e.id FROM emergency_contacts e
           JOIN drivers d ON e.driver_id = d.id
           WHERE e.id = ? AND d.user_id = ?''',
        (contact_id, current_user.id),
    ).fetchone()
    if row:
        conn.execute('DELETE FROM emergency_contacts WHERE id = ?', (contact_id,))
        conn.commit()
        flash('Emergency contact removed.', 'success')
    conn.close()
    return redirect(url_for('emergency_contacts_page'))


# ============ Profile (account + driver details) ============

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip().lower()
        vehicle_info = request.form.get('vehicle_info', '').strip() or None

        if not full_name or not email or not phone:
            flash('Name, email, and phone are required.', 'error')
            ctx = _profile_context(conn, current_user.id)
            conn.close()
            return render_template('profile.html', **ctx)

        user_row = conn.execute(
            'SELECT profile_picture FROM users WHERE id = ?', (current_user.id,)
        ).fetchone()
        old_pic = user_row['profile_picture'] if user_row else None
        upload = request.files.get('profile_picture')
        pic_result = _save_profile_picture(current_user.id, upload) if upload and upload.filename else None

        if pic_result == 'invalid_type':
            flash('Profile picture must be PNG, JPG, WEBP, or GIF.', 'error')
            ctx = _profile_context(conn, current_user.id)
            conn.close()
            return render_template('profile.html', **ctx)

        new_pic = pic_result if pic_result and pic_result != 'invalid_type' else old_pic
        try:
            conn.execute(
                'UPDATE users SET full_name=?, phone=?, email=?, profile_picture=? WHERE id=?',
                (full_name, phone, email, new_pic, current_user.id),
            )
            sync_driver_from_profile(
                conn, current_user.id, full_name, phone, email, vehicle_info,
            )
            conn.commit()
            if pic_result and pic_result != 'invalid_type' and old_pic and old_pic != pic_result:
                _delete_profile_picture_file(old_pic)
            row = conn.execute(
                'SELECT id, email, full_name, phone, onboarding_done FROM users WHERE id = ?',
                (current_user.id,),
            ).fetchone()
            conn.close()
            login_user(row_user(row))
            flash('Profile updated.', 'success')
            return redirect(url_for('profile'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('That email is already in use.', 'error')
            conn = get_db()
            ctx = _profile_context(conn, current_user.id)
            conn.close()
            return render_template('profile.html', **ctx)

    ctx = _profile_context(conn, current_user.id)
    conn.close()
    return render_template('profile.html', **ctx)


@app.route('/profile/picture/delete', methods=['POST'])
@login_required
def profile_picture_delete():
    conn = get_db()
    row = conn.execute(
        'SELECT profile_picture FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    if row and row['profile_picture']:
        old_pic = row['profile_picture']
        conn.execute(
            'UPDATE users SET profile_picture = NULL WHERE id = ?', (current_user.id,)
        )
        conn.commit()
        _delete_profile_picture_file(old_pic)
        flash('Profile picture removed.', 'success')
    conn.close()
    return redirect(url_for('profile'))


@app.route('/profile/password', methods=['POST'])
@login_required
def profile_password():
    current = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    conn = get_db()
    row = conn.execute(
        'SELECT password_hash FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    if not row or not check_password_hash(row['password_hash'], current):
        conn.close()
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('profile'))
    if len(new_pw) < 8:
        conn.close()
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('profile'))
    conn.execute(
        'UPDATE users SET password_hash = ? WHERE id = ?',
        (generate_password_hash(new_pw), current_user.id),
    )
    conn.commit()
    conn.close()
    flash('Password changed.', 'success')
    return redirect(url_for('profile'))


# ============ Alerts log ============

@app.route('/alerts')
@login_required
def alerts_log():
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.*, datetime(a.created_at, ?) AS created_at_local, dr.name AS driver_name FROM alert_events a
           LEFT JOIN drivers dr ON a.driver_id = dr.id
           WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT 200''',
        (LOCAL_TIME_OFFSET, current_user.id),
    ).fetchall()
    conn.close()
    return render_template('alerts.html', alerts=[dict(r) for r in rows])


# ============ REST API (IoT) ============

def _api_driver(identifier):
    conn = get_db()
    if identifier.isdigit():
        driver = conn.execute('SELECT * FROM drivers WHERE id = ?', (int(identifier),)).fetchone()
    else:
        driver = conn.execute(
            'SELECT * FROM drivers WHERE driver_code = ? OR device_id = ?', (identifier, identifier)
        ).fetchone()
    conn.close()
    return driver


@app.route('/api/drivers')
def api_list_drivers():
    conn = get_db()
    drivers = conn.execute('SELECT id, driver_code, name, phone, device_id FROM drivers').fetchall()
    conn.close()
    return jsonify([dict(r) for r in drivers])


@app.route('/api/driver/<identifier>/emergency-contacts')
def api_get_emergency_contacts(identifier):
    driver = _api_driver(identifier)
    if not driver:
        return jsonify({'error': 'Driver not found', 'phones': []}), 404

    conn = get_db()
    contacts = conn.execute(
        'SELECT name, phone, is_primary FROM emergency_contacts WHERE driver_id = ? ORDER BY is_primary DESC',
        (driver['id'],),
    ).fetchall()
    conn.close()
    phones = [{'name': r['name'], 'phone': r['phone'], 'is_primary': bool(r['is_primary'])} for r in contacts]
    return jsonify({'driver_id': driver['id'], 'driver_code': driver['driver_code'], 'phones': phones})


@app.route('/api/driver/<identifier>/emergency-phones')
def api_get_emergency_phones_only(identifier):
    resp = api_get_emergency_contacts(identifier)
    if isinstance(resp, tuple):
        return resp
    data = resp.get_json()
    phones = [p['phone'] for p in data.get('phones', [])]
    return jsonify({'phones': phones})


@app.route('/api/alert', methods=['POST'])
def api_log_alert():
    """
    Raspberry Pi / IoT can POST when drowsiness triggers GSM notification.
    JSON: { "driver_id": 1 } or { "driver_code": "DR001" } or
    { "device_id": "ESP32_001" }, optional "message", optional "alert_type" ("SMS" or "CALL"),
    optional "recipients" (string or list)
    """
    data = request.get_json(silent=True) or {}
    did = data.get('driver_id')
    dcode = data.get('driver_code')
    dev = data.get('device_id')
    recipients_payload = data.get('recipients')
    alert_type_raw = str(data.get('alert_type') or 'SMS').strip().upper()
    alert_type = 'CALL' if alert_type_raw == 'CALL' else 'SMS'
    message = (data.get('message') or 'Drowsiness detected — GSM alert sent to emergency contacts.').strip()

    conn = get_db()
    driver = None
    if did is not None:
        driver = conn.execute('SELECT * FROM drivers WHERE id = ?', (int(did),)).fetchone()
    elif dcode:
        driver = conn.execute(
            'SELECT * FROM drivers WHERE driver_code = ?', (str(dcode),)
        ).fetchone()
    elif dev:
        driver = conn.execute(
            'SELECT * FROM drivers WHERE device_id = ?', (str(dev),)
        ).fetchone()

    if not driver:
        conn.close()
        return jsonify({'ok': False, 'error': 'driver not found'}), 404

    uid = driver['user_id']
    alert_recipients = _format_alert_recipients(conn, driver['id'], alert_type, recipients_payload)
    conn.execute(
        'INSERT INTO alert_events (user_id, driver_id, alert_type, alert_recipients, message, source) VALUES (?, ?, ?, ?, ?, ?)',
        (uid, driver['id'], alert_type, alert_recipients, message, 'iot'),
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'driver_id': driver['id'], 'driver_code': driver['driver_code'], 'recipients': alert_recipients})


@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'service': 'smartdrive'})


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '1').lower() in ('1', 'true', 'yes')
    print(f'SmartDrive App running at http://127.0.0.1:{port}')
    app.run(host='0.0.0.0', port=port, debug=debug)
