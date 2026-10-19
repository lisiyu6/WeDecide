"""Small SQLite store. Mutating a room is an atomic bounded-document transaction."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import secrets
import sqlite3
import time
from .config import DATA_DIR, DB_PATH, DEFAULT_SETTINGS


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Connection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA cache_size=-2048")
    return db


def init():
    os.umask(0o077)
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL, updated REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE, user_id TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS messages_room_user ON messages(room_id,user_id,id);
        CREATE INDEX IF NOT EXISTS rooms_updated ON rooms(updated);
        CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
        ''')
        db.execute("INSERT OR IGNORE INTO settings VALUES ('config', ?)", (dumps(DEFAULT_SETTINGS),))
    os.chmod(DB_PATH, 0o600)


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def settings(db=None):
    if db is None:
        with connect() as conn:
            return settings(conn)
    row = db.execute("SELECT value FROM settings WHERE key='config'").fetchone()
    return {**deepcopy(DEFAULT_SETTINGS), **json.loads(row[0])}


def load_room(db, key):
    row = db.execute("SELECT data FROM rooms WHERE id=? OR code=?", (key, key.upper())).fetchone()
    return json.loads(row[0]) if row else None


def save_room(db, room, touch=True):
    room["revision"] += 1
    if touch:
        room["updated"] = time.time()
    db.execute("UPDATE rooms SET state=?,revision=?,updated=?,data=? WHERE id=?", (room["state"], room["revision"], room["updated"], dumps(room), room["id"]))


def new_id():
    return secrets.token_urlsafe(12)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session(token):
    if not token:
        return None
    with connect() as db:
        row = db.execute("SELECT * FROM sessions WHERE token=? AND expires>?", (digest(token), time.time())).fetchone()
    return dict(row) if row else None


def make_session(admin=False, user_id=None):
    token = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (digest(token), user_id or new_id(), int(admin), time.time() + (43200 if admin else 2592000)))
    return token


def append_message(db, room_id, user_id, role, kind, content, metadata=None):
    cursor = db.execute("INSERT INTO messages(room_id,user_id,role,kind,content,metadata,created) VALUES(?,?,?,?,?,?,?)", (room_id, user_id, role, kind, content, dumps(metadata or {}), time.time()))
    # Each room retains at most 2,000 entries on disk; reading is always paginated.
    db.execute("DELETE FROM messages WHERE room_id=? AND id < COALESCE((SELECT id FROM messages WHERE room_id=? ORDER BY id DESC LIMIT 1 OFFSET 1999),0)", (room_id, room_id))
    return cursor.lastrowid


def messages(room_id, user_id, before=None, limit=50):
    with connect() as db:
        rows = db.execute("SELECT * FROM messages WHERE room_id=? AND (user_id=? OR kind='shared') AND id<? ORDER BY id DESC LIMIT ?", (room_id, user_id, before or 9223372036854775807, limit)).fetchall()
    return [{**dict(r), "metadata": json.loads(r["metadata"])} for r in reversed(rows)]
