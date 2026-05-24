"""
Database layer — SQLite (local dev) or PostgreSQL (Render DATABASE_URL).

Set DATABASE_URL on Render to attach a Render Postgres instance.
Leave unset locally to keep using app/smartdrive.db.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from db_config import get_database_path

LOCAL_TIME_OFFSET = '+8 hours'
DATABASE = get_database_path()


def use_postgres() -> bool:
    return bool((os.environ.get('DATABASE_URL') or '').strip())


def _postgres_url() -> str:
    url = os.environ['DATABASE_URL'].strip()
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


class DbCursor:
    def __init__(self, cursor, backend: str):
        self._cursor = cursor
        self._backend = backend

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._backend == 'postgres':
            return row
        return row

    def fetchall(self):
        return self._cursor.fetchall()


class DbConnection:
    """SQLite-like connection wrapper (works with ? placeholders everywhere)."""

    def __init__(self, raw_conn, backend: str):
        self._conn = raw_conn
        self._backend = backend

    def execute(self, sql: str, params=()):
        if self._backend == 'postgres':
            import psycopg2.extras

            sql = sql.replace('?', '%s')
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            return DbCursor(cur, self._backend)
        return self._conn.execute(sql, params)

    def executescript(self, sql: str):
        if self._backend == 'postgres':
            for statement in sql.split(';'):
                stmt = statement.strip()
                if stmt:
                    self.execute(stmt)
            return
        self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db() -> DbConnection:
    if use_postgres():
        import psycopg2

        raw = psycopg2.connect(_postgres_url())
        raw.autocommit = False
        return DbConnection(raw, 'postgres')

    raw = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    return DbConnection(raw, 'sqlite')


def table_columns(conn: DbConnection, name: str) -> set[str]:
    if use_postgres():
        rows = conn.execute(
            '''SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = ?''',
            (name,),
        ).fetchall()
        return {r['column_name'] for r in rows}

    return {r[1] for r in conn.execute(f'PRAGMA table_info({name})').fetchall()}


def created_at_local_select(alias: str = 'a') -> tuple[str, list]:
    """SQL fragment + extra params for Malaysia local time in alert queries."""
    if use_postgres():
        return f'({alias}.created_at + INTERVAL \'8 hours\') AS created_at_local', []
    return f'datetime({alias}.created_at, ?) AS created_at_local', [LOCAL_TIME_OFFSET]


def _init_sqlite(conn: DbConnection):
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
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    ''')


def _init_postgres(conn: DbConnection):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL,
            phone TEXT,
            onboarding_done INTEGER DEFAULT 0,
            firebase_uid TEXT,
            profile_picture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS drivers (
            id SERIAL PRIMARY KEY,
            driver_code TEXT UNIQUE,
            user_id INTEGER REFERENCES users (id),
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            vehicle_info TEXT,
            device_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS emergency_contacts (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER NOT NULL REFERENCES drivers (id),
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            relationship TEXT,
            is_primary INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS alert_events (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users (id),
            driver_id INTEGER REFERENCES drivers (id),
            alert_type TEXT DEFAULT 'SMS',
            alert_recipients TEXT,
            message TEXT NOT NULL,
            source TEXT DEFAULT 'iot',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users (id),
            token_hash TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')


def _run_migrations(conn: DbConnection):
    driver_cols = table_columns(conn, 'drivers')
    if 'user_id' not in driver_cols:
        conn.execute('ALTER TABLE drivers ADD COLUMN user_id INTEGER REFERENCES users (id)')
    if 'driver_code' not in driver_cols:
        conn.execute('ALTER TABLE drivers ADD COLUMN driver_code TEXT')
        rows = conn.execute(
            'SELECT id FROM drivers WHERE driver_code IS NULL OR TRIM(driver_code) = \'\' ORDER BY id'
        ).fetchall()
        for idx, row in enumerate(rows, start=1):
            conn.execute(
                'UPDATE drivers SET driver_code = ? WHERE id = ?',
                (f'DR{idx:03d}', row['id']),
            )

    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_drivers_driver_code ON drivers(driver_code)')

    user_cols = table_columns(conn, 'users')
    if 'onboarding_done' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN onboarding_done INTEGER DEFAULT 0')
    if 'firebase_uid' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN firebase_uid TEXT')
    if 'profile_picture' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN profile_picture TEXT')

    alert_cols = table_columns(conn, 'alert_events')
    if 'alert_type' not in alert_cols:
        conn.execute("ALTER TABLE alert_events ADD COLUMN alert_type TEXT DEFAULT 'SMS'")
        conn.execute(
            "UPDATE alert_events SET alert_type = 'SMS' WHERE alert_type IS NULL OR TRIM(alert_type) = ''"
        )
    if 'alert_recipients' not in alert_cols:
        conn.execute('ALTER TABLE alert_events ADD COLUMN alert_recipients TEXT')
        conn.execute("UPDATE alert_events SET alert_recipients = '' WHERE alert_recipients IS NULL")

    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_emergency_primary_per_driver '
        'ON emergency_contacts(driver_id) WHERE is_primary = 1'
    )


def init_schema():
    conn = get_db()
    try:
        if use_postgres():
            _init_postgres(conn)
        else:
            _init_sqlite(conn)
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def parse_expires_at(value):
    """Normalize expires_at from SQLite text or Postgres timestamp."""
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace('Z', '+00:00').replace('+00:00', ''))
    return value


def is_unique_violation(exc: Exception) -> bool:
    import sqlite3

    if isinstance(exc, sqlite3.IntegrityError):
        return True
    if use_postgres():
        import psycopg2

        return isinstance(exc, psycopg2.IntegrityError)
    return False
