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


# ---------------------------------------------------------------------------
# Local time helpers.
# The admin UI sends <input type="datetime-local"> values, which are LOCAL wall
# clock. Storing "now" as UTC made those two mismatch by the TZ offset, so
# overdue checks fired late and displayed times looked wrong. Everything the
# user sees is now written in local wall-clock using tz_offset_minutes.
# ---------------------------------------------------------------------------
_TZ_CACHE = {"val": None, "at": 0.0}
DEFAULT_TZ_OFFSET = 120  # SAST (UTC+2)


def tz_offset_minutes(force: bool = False) -> int:
    import time as _t
    if not force and _TZ_CACHE["val"] is not None and (_t.time() - _TZ_CACHE["at"]) < 30:
        return _TZ_CACHE["val"]
    val = DEFAULT_TZ_OFFSET
    try:
        with get_db() as conn:
            row = conn.execute("SELECT tz_offset_minutes FROM settings WHERE id = 1").fetchone()
        if row is not None and row[0] is not None:
            val = int(row[0])
    except Exception:  # noqa: BLE001 - table/column may not exist yet
        pass
    _TZ_CACHE["val"] = val
    _TZ_CACHE["at"] = _t.time()
    return val


def local_dt() -> dt.datetime:
    return dt.datetime.utcnow() + dt.timedelta(minutes=tz_offset_minutes())


def now_local() -> str:
    return local_dt().isoformat(timespec="seconds")


def parse_ts(value):
    """Parse the timestamp formats we store / receive. Returns None if unusable."""
    if not value:
        return None
    s = str(value).strip().replace(" ", "T")
    s = s.split("+")[0].split("Z")[0].split(".")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def minutes_between(a: str, b: str):
    """Whole minutes from a -> b. None if either side is unparseable."""
    da, db_ = parse_ts(a), parse_ts(b)
    if not da or not db_:
        return None
    return int((db_ - da).total_seconds() // 60)


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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'staff',        -- admin | staff
    permissions TEXT DEFAULT '[]',    -- JSON list of extra grants (staff only)
    active INTEGER DEFAULT 1,
    created_at TEXT,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- overdue_checkout
    stay_id INTEGER,
    room_id INTEGER,
    title TEXT DEFAULT '',
    message TEXT DEFAULT '',
    severity TEXT DEFAULT 'warn',    -- warn | alert
    created_at TEXT,
    acknowledged_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts (acknowledged_at, created_at);
CREATE INDEX IF NOT EXISTS idx_stays_status ON stays (status);
"""


MIGRATIONS = [
    "ALTER TABLE settings ADD COLUMN ha_enabled INTEGER DEFAULT 0",
    "ALTER TABLE settings ADD COLUMN ha_url TEXT DEFAULT ''",
    "ALTER TABLE settings ADD COLUMN ha_webhook_id TEXT DEFAULT ''",
    "ALTER TABLE settings ADD COLUMN ha_room_prefix TEXT DEFAULT 'Room '",
    "ALTER TABLE settings ADD COLUMN ha_use_room_name INTEGER DEFAULT 0",
    "ALTER TABLE settings ADD COLUMN ha_sync_minutes INTEGER DEFAULT 15",
    "ALTER TABLE settings ADD COLUMN ha_token TEXT DEFAULT ''",
    # --- v1.4.0: overdue checkout alerts + room QR lockout ---
    "ALTER TABLE stays ADD COLUMN checked_out_at TEXT",
    "ALTER TABLE stays ADD COLUMN overdue_notified_at TEXT",
    "ALTER TABLE settings ADD COLUMN tz_offset_minutes INTEGER DEFAULT 120",
    "ALTER TABLE settings ADD COLUMN overdue_alerts_enabled INTEGER DEFAULT 1",
    "ALTER TABLE settings ADD COLUMN overdue_grace_minutes INTEGER DEFAULT 15",
    "ALTER TABLE settings ADD COLUMN overdue_repeat_hours INTEGER DEFAULT 6",
    "ALTER TABLE settings ADD COLUMN room_lock_on_checkout INTEGER DEFAULT 1",
    "ALTER TABLE settings ADD COLUMN room_lock_grace_minutes INTEGER DEFAULT 0",
    "ALTER TABLE settings ADD COLUMN room_lock_message TEXT DEFAULT "
    "'Your stay has ended. Please contact reception if you need anything.'",
    # --- v1.5.0: staff accounts ---
    "ALTER TABLE sessions ADD COLUMN user_id INTEGER",
]


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for mig in MIGRATIONS:
            try:
                conn.execute(mig)
            except sqlite3.OperationalError:
                pass  # column already exists
        # seed settings row
        row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if not row:
            default_pw = os.environ.get("ADMIN_PASSWORD", "admin")
            conn.execute(
                "INSERT INTO settings (id, admin_password, updated_at) VALUES (1, ?, ?)",
                (hash_password(default_pw), _now()),
            )
        _seed_admin_user(conn)


def _seed_admin_user(conn):
    """First run under v1.5.0: turn the single admin password into an
    'admin' account. Any pre-existing session is dropped so everyone signs
    in again against the new accounts table."""
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    row = conn.execute("SELECT admin_password FROM settings WHERE id = 1").fetchone()
    pw_hash = row["admin_password"] if row and row["admin_password"] else \
        hash_password(os.environ.get("ADMIN_PASSWORD", "admin"))
    conn.execute(
        """INSERT INTO users (username, display_name, password_hash, role,
             permissions, active, created_at)
           VALUES ('admin', 'Administrator', ?, 'admin', '[]', 1, ?)""",
        (pw_hash, _now()),
    )
    conn.execute("DELETE FROM sessions")


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, now_local()),
        )
    return token


def session_user(token: str):
    """Resolve a session token to its (active) user row, or None."""
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND u.active = 1""",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def session_valid(token: str) -> bool:
    return session_user(token) is not None


def drop_sessions_for_user(user_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def destroy_session(token: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
