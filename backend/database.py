"""
GuestIQ - SQLite database layer.
Plain stdlib sqlite3 (matches the AssetIQ FastAPI/SQLite pattern).
DB lives in ./data/ which is bind-mounted so it survives Docker rebuilds.
"""
import os
import sqlite3
import hashlib
import secrets
import datetime as dt
from contextlib import contextmanager

DATA_DIR = os.environ.get("GUESTIQ_DATA", os.path.join(os.getcwd(), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "guestiq.db")


def _now():
    return dt.datetime.utcnow().isoformat(timespec="seconds")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Password hashing (stdlib pbkdf2, no external deps)
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
        return secrets.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Schema. Additive-only migrations via "ALTER TABLE ... " guarded with try.
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    hotel_name TEXT DEFAULT 'My Hotel',
    address TEXT DEFAULT '',
    public_url TEXT DEFAULT '',
    reception_phone TEXT DEFAULT '',
    restaurant_name TEXT DEFAULT 'Restaurant',
    restaurant_phone TEXT DEFAULT '',
    menu_url TEXT DEFAULT '',
    emergency_number TEXT DEFAULT '',
    checkout_time TEXT DEFAULT '10:00',
    welcome_message TEXT DEFAULT 'Welcome! We hope you enjoy your stay.',
    admin_password TEXT DEFAULT '',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_number TEXT NOT NULL,
    room_name TEXT DEFAULT '',
    floor TEXT DEFAULT '',
    room_code TEXT UNIQUE NOT NULL,
    wifi_ssid TEXT DEFAULT '',
    wifi_password TEXT DEFAULT '',
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'available',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS guests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    id_number TEXT DEFAULT '',
    address TEXT DEFAULT '',
    vehicle_reg TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS stays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guest_id INTEGER NOT NULL,
    room_id INTEGER,
    check_in_at TEXT,
    check_out_at TEXT,
    num_guests INTEGER DEFAULT 1,
    status TEXT DEFAULT 'pending',   -- pending | checked_in | checked_out | cancelled
    source TEXT DEFAULT 'self',      -- self | admin
    created_at TEXT,
    FOREIGN KEY (guest_id) REFERENCES guests(id) ON DELETE CASCADE,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    created_at TEXT
);
"""


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # seed settings row
        row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if not row:
            default_pw = os.environ.get("ADMIN_PASSWORD", "admin")
            conn.execute(
                "INSERT INTO settings (id, admin_password, updated_at) VALUES (1, ?, ?)",
                (hash_password(default_pw), _now()),
            )


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def create_session() -> str:
    token = secrets.token_urlsafe(32)
    with get_db() as conn:
        conn.execute("INSERT INTO sessions (token, created_at) VALUES (?, ?)", (token, _now()))
    return token


def session_valid(token: str) -> bool:
    if not token:
        return False
    with get_db() as conn:
        return conn.execute("SELECT 1 FROM sessions WHERE token = ?", (token,)).fetchone() is not None


def destroy_session(token: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
