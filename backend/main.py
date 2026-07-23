"""
GuestIQ - hotel guest check-in + in-room info system.
FastAPI + SQLite. Serves an admin dashboard and two QR-driven guest flows:
  1. /checkin        -> guest self check-in form (arrival QR)
  2. /room/{code}    -> in-room info: wifi, restaurant, menu, etc. (per-room QR)
"""
import os
import datetime as dt
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header, Depends, UploadFile, File
from fastapi.responses import (
    JSONResponse, StreamingResponse, FileResponse, RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import io

from . import database as db
from .qr import make_qr_png
from . import updater
from . import ha_sync
from . import notifications as notif
from . import auth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")

app = FastAPI(title="GuestIQ", version=updater.get_local_version())


@app.on_event("startup")
def _startup():
    db.init_db()
    _fix_stored_urls()
    ha_sync.start_periodic()
    notif.start_watcher()


def _now():
    """Local wall-clock, matching the <input type=datetime-local> values the
    admin UI sends. See database.tz_offset_minutes."""
    return db.now_local()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    password: str
    username: Optional[str] = None


@app.post("/api/login")
def login(body: LoginIn):
    username = (body.username or "admin").strip().lower()
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = ?", (username,)
        ).fetchone()
    if not row or not db.verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    if not row["active"]:
        raise HTTPException(status_code=403, detail="This account has been disabled")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
                     (db.now_local(), row["id"]))
    return {"token": db.create_session(row["id"]), "user": auth.public_user(dict(row))}


@app.post("/api/logout")
def logout(user: dict = Depends(auth.require_user)):
    db.destroy_session(user["_token"])
    return {"ok": True}


@app.get("/api/me")
def whoami(user: dict = Depends(auth.require_user)):
    """Who is signed in and what they're allowed to do — drives the whole UI."""
    return {**auth.public_user(user),
            "catalogue": auth.PERMISSIONS,
            "base_capabilities": auth.BASE_CAPABILITIES}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsIn(BaseModel):
    hotel_name: Optional[str] = None
    address: Optional[str] = None
    public_url: Optional[str] = None
    reception_phone: Optional[str] = None
    restaurant_name: Optional[str] = None
    restaurant_phone: Optional[str] = None
    menu_url: Optional[str] = None
    emergency_number: Optional[str] = None
    checkout_time: Optional[str] = None
    welcome_message: Optional[str] = None
    # v1.4.0
    tz_offset_minutes: Optional[int] = None
    overdue_alerts_enabled: Optional[bool] = None
    overdue_grace_minutes: Optional[int] = None
    overdue_repeat_hours: Optional[int] = None
    room_lock_on_checkout: Optional[bool] = None
    room_lock_grace_minutes: Optional[int] = None
    room_lock_message: Optional[str] = None


class PasswordIn(BaseModel):
    new_password: str


URL_FIELDS = ("public_url", "menu_url")


def _normalise_url(value: str) -> str:
    """A URL without a scheme is resolved by the browser as a path RELATIVE to
    the page it sits on — so 'lodge.co.za/menu' on /room/3-kudu became
    /room/lodge.co.za/menu and the guest got "this code is invalid".
    Anything that isn't a scheme, mailto: or tel: gets https:// put on it."""
    v = (value or "").strip()
    if not v:
        return ""
    low = v.lower()
    if low.startswith(("http://", "https://", "mailto:", "tel:")):
        return v
    if v.startswith("/"):          # deliberate same-site path
        return v
    return "https://" + v.lstrip("/")


def _fix_stored_urls():
    """One-off repair for settings saved before v1.4.3."""
    try:
        with db.get_db() as conn:
            row = conn.execute(
                f"SELECT {', '.join(URL_FIELDS)} FROM settings WHERE id = 1"
            ).fetchone()
            if not row:
                return
            fixes = {f: _normalise_url(row[f]) for f in URL_FIELDS
                     if row[f] and _normalise_url(row[f]) != row[f]}
            if fixes:
                sets = ", ".join(f"{k} = ?" for k in fixes)
                conn.execute(f"UPDATE settings SET {sets} WHERE id = 1", tuple(fixes.values()))
    except Exception:  # noqa: BLE001 - never block startup
        pass


def _settings_row():
    with db.get_db() as conn:
        return dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())


@app.get("/api/settings")
def get_settings(user: dict = Depends(auth.require_user)):
    """Readable by any signed-in user (the console needs hotel name, checkout
    time etc.), but the automation hub URL and token are stripped unless the
    account is allowed to manage automation."""
    s = _settings_row()
    s.pop("admin_password", None)
    s["logo_url"] = _logo_url(s)
    if "automation" not in auth.perms_of(user):
        for k in AUTOMATION_FIELDS:
            s.pop(k, None)
    return s


@app.put("/api/settings")
def update_settings(body: SettingsIn, user: dict = Depends(auth.require_perm("settings"))):
    fields = {k: (int(v) if isinstance(v, bool) else v)
              for k, v in body.dict().items() if v is not None}
    for f in URL_FIELDS:
        if f in fields:
            fields[f] = _normalise_url(fields[f])
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.get_db() as conn:
            conn.execute(
                f"UPDATE settings SET {sets}, updated_at = ? WHERE id = 1",
                (*fields.values(), db.now_local()),
            )
        db.tz_offset_minutes(force=True)  # drop the cached offset
    return get_settings(user)


@app.post("/api/settings/password")
def change_password(body: PasswordIn, user: dict = Depends(auth.require_admin_role)):
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password too short")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (db.hash_password(body.new_password), user["id"]))
        conn.execute(
            "UPDATE settings SET admin_password = ?, updated_at = ? WHERE id = 1",
            (db.hash_password(body.new_password), _now()),
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Property logo — shown on every QR-scanned guest page
# ---------------------------------------------------------------------------
LOGO_DIR = os.path.join(db.DATA_DIR, "branding")
LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}
LOGO_MAX_BYTES = 3 * 1024 * 1024   # 3 MB


def _logo_url(s: dict) -> str:
    """Cache-busted public URL, or '' when no logo has been uploaded."""
    if not s.get("logo_file"):
        return ""
    stamp = (s.get("logo_updated") or "").replace(":", "").replace("-", "")
    return f"/api/logo?v={stamp}" if stamp else "/api/logo"


@app.post("/api/settings/logo")
async def upload_logo(file: UploadFile = File(...),
                      user: dict = Depends(auth.require_perm("settings"))):
    ext = LOGO_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(400, "Use a PNG, JPG, WEBP, GIF or SVG image")
    data = await file.read()
    if not data:
        raise HTTPException(400, "That file is empty")
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(400, "Logo must be smaller than 3 MB")

    os.makedirs(LOGO_DIR, exist_ok=True)
    for old_file in os.listdir(LOGO_DIR):           # only ever keep one
        try:
            os.remove(os.path.join(LOGO_DIR, old_file))
        except OSError:
            pass
    name = f"logo{ext}"
    with open(os.path.join(LOGO_DIR, name), "wb") as fh:
        fh.write(data)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE settings SET logo_file = ?, logo_updated = ?, updated_at = ? WHERE id = 1",
            (name, _now(), _now()),
        )
    return {"ok": True, "logo_url": _logo_url(_settings_row())}


@app.delete("/api/settings/logo")
def delete_logo(user: dict = Depends(auth.require_perm("settings"))):
    s = _settings_row()
    if s.get("logo_file"):
        try:
            os.remove(os.path.join(LOGO_DIR, s["logo_file"]))
        except OSError:
            pass
    with db.get_db() as conn:
        conn.execute(
            "UPDATE settings SET logo_file = '', logo_updated = '', updated_at = ? WHERE id = 1",
            (_now(),),
        )
    return {"ok": True}


@app.get("/api/logo")
def get_logo():
    """Public: the guest pages are reached by QR with no login."""
    s = _settings_row()
    name = s.get("logo_file")
    path = os.path.join(LOGO_DIR, name) if name else ""
    if not name or not os.path.exists(path):
        raise HTTPException(404, "No logo uploaded")
    media = next((m for m, e in LOGO_TYPES.items() if name.endswith(e)), "image/png")
    return FileResponse(
        path,
        media_type=media,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            # an uploaded SVG must never be able to run anything
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
def _slugify(text: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "room"


class RoomIn(BaseModel):
    room_number: str
    room_name: Optional[str] = ""
    floor: Optional[str] = ""
    wifi_ssid: Optional[str] = ""
    wifi_password: Optional[str] = ""
    description: Optional[str] = ""


@app.get("/api/rooms")
def list_rooms(user: dict = Depends(auth.require_user)):
    with db.get_db() as conn:
        rooms = [dict(r) for r in conn.execute("SELECT * FROM rooms ORDER BY room_number").fetchall()]
        # attach current occupant
        for r in rooms:
            occ = conn.execute(
                """SELECT g.full_name, s.check_out_at FROM stays s
                   JOIN guests g ON g.id = s.guest_id
                   WHERE s.room_id = ? AND s.status = 'checked_in'
                   ORDER BY s.id DESC LIMIT 1""",
                (r["id"],),
            ).fetchone()
            r["occupant"] = dict(occ) if occ else None
    return rooms


@app.get("/api/rooms/availability")
def room_availability(user: dict = Depends(auth.require_user)):
    """Used by the check-in dialogs to refuse politely when the lodge is full."""
    with db.get_db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM rooms").fetchone()["c"]
        occupied = conn.execute(
            """SELECT COUNT(DISTINCT room_id) c FROM stays
               WHERE status = 'checked_in' AND room_id IS NOT NULL"""
        ).fetchone()["c"]
    return {"total": total, "occupied": occupied,
            "available": max(0, total - occupied), "full": total > 0 and occupied >= total}


@app.post("/api/rooms")
def create_room(body: RoomIn, user: dict = Depends(auth.require_perm("rooms"))):
    base = _slugify(f"{body.room_number}-{body.room_name}" if body.room_name else body.room_number)
    with db.get_db() as conn:
        code, n = base, 1
        while conn.execute("SELECT 1 FROM rooms WHERE room_code = ?", (code,)).fetchone():
            n += 1
            code = f"{base}-{n}"
        cur = conn.execute(
            """INSERT INTO rooms (room_number, room_name, floor, room_code,
                 wifi_ssid, wifi_password, description, status, created_at)
               VALUES (?,?,?,?,?,?,?, 'available', ?)""",
            (body.room_number, body.room_name, body.floor, code,
             body.wifi_ssid, body.wifi_password, body.description, _now()),
        )
        rid = cur.lastrowid
        return dict(conn.execute("SELECT * FROM rooms WHERE id = ?", (rid,)).fetchone())


@app.put("/api/rooms/{room_id}")
def update_room(room_id: int, body: RoomIn, user: dict = Depends(auth.require_perm("rooms"))):
    with db.get_db() as conn:
        if not conn.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone():
            raise HTTPException(404, "Room not found")
        conn.execute(
            """UPDATE rooms SET room_number=?, room_name=?, floor=?,
                 wifi_ssid=?, wifi_password=?, description=? WHERE id=?""",
            (body.room_number, body.room_name, body.floor,
             body.wifi_ssid, body.wifi_password, body.description, room_id),
        )
        return dict(conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone())


@app.delete("/api/rooms/{room_id}")
def delete_room(room_id: int, user: dict = Depends(auth.require_perm("rooms_delete"))):
    with db.get_db() as conn:
        conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Guest self check-in  (PUBLIC - reached via arrival QR)
# ---------------------------------------------------------------------------
class CheckinIn(BaseModel):
    full_name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    id_number: Optional[str] = ""
    address: Optional[str] = ""
    vehicle_reg: Optional[str] = ""
    num_guests: Optional[int] = 1


def _find_or_create_guest(conn, body: CheckinIn, guest_id: Optional[int] = None):
    """Save guest for future: an explicitly picked guest_id wins, otherwise
    match on id_number, then email, then phone.

    Blank incoming fields never overwrite what is already on record — a
    returning guest picked from the contact list keeps their address and
    vehicle reg even though the quick check-in form doesn't ask for them.
    """
    row = None
    if guest_id:
        row = conn.execute("SELECT * FROM guests WHERE id = ?", (guest_id,)).fetchone()
    if not row:
        for field in ("id_number", "email", "phone"):
            val = getattr(body, field)
            if val:
                row = conn.execute(
                    f"SELECT * FROM guests WHERE {field} = ? AND {field} != '' LIMIT 1", (val,)
                ).fetchone()
                if row:
                    break
    if row:
        gid = row["id"]
        keep = lambda new, col: (new if (new or "").strip() else (row[col] or ""))  # noqa: E731
        conn.execute(
            """UPDATE guests SET full_name=?, email=?, phone=?, id_number=?,
                 address=?, vehicle_reg=?, updated_at=? WHERE id=?""",
            (keep(body.full_name, "full_name"), keep(body.email, "email"),
             keep(body.phone, "phone"), keep(body.id_number, "id_number"),
             keep(body.address, "address"), keep(body.vehicle_reg, "vehicle_reg"),
             _now(), gid),
        )
        return gid, False
    cur = conn.execute(
        """INSERT INTO guests (full_name, email, phone, id_number, address,
             vehicle_reg, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        (body.full_name, body.email, body.phone, body.id_number,
         body.address, body.vehicle_reg, _now(), _now()),
    )
    return cur.lastrowid, True


@app.post("/api/checkin")
def guest_checkin(body: CheckinIn):
    if not body.full_name.strip():
        raise HTTPException(400, "Name is required")
    with db.get_db() as conn:
        gid, is_new = _find_or_create_guest(conn, body)
        conn.execute(
            """INSERT INTO stays (guest_id, num_guests, status, source, created_at)
               VALUES (?,?, 'pending', 'self', ?)""",
            (gid, body.num_guests or 1, _now()),
        )
    return {"ok": True, "returning_guest": not is_new}


# ---------------------------------------------------------------------------
# Guests (admin)
# ---------------------------------------------------------------------------
class GuestIn(BaseModel):
    full_name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    id_number: Optional[str] = ""
    address: Optional[str] = ""
    vehicle_reg: Optional[str] = ""
    notes: Optional[str] = ""


GUEST_SELECT = """
    SELECT g.*,
      (SELECT COUNT(*) FROM stays s WHERE s.guest_id = g.id
         AND s.status IN ('checked_in','checked_out')) AS visits,
      (SELECT MAX(IFNULL(s.checked_out_at, s.check_in_at)) FROM stays s
         WHERE s.guest_id = g.id AND s.status IN ('checked_in','checked_out')) AS last_stay,
      (SELECT CASE WHEN COUNT(*) > 0 THEN 1 ELSE 0 END FROM stays s
         WHERE s.guest_id = g.id AND s.status = 'checked_in') AS in_house
    FROM guests g"""


@app.get("/api/guests")
def list_guests(q: Optional[str] = None, limit: Optional[int] = None,
                user: dict = Depends(auth.require_user)):
    sql = GUEST_SELECT
    params: tuple = ()
    if q:
        like = f"%{q}%"
        sql += """ WHERE g.full_name LIKE ? OR g.email LIKE ?
                     OR g.phone LIKE ? OR g.id_number LIKE ?"""
        params = (like, like, like, like)
    sql += " ORDER BY g.updated_at DESC"
    if limit:
        sql += " LIMIT ?"
        params = (*params, int(limit))
    with db.get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


class GuestCreateIn(GuestIn):
    pass


@app.post("/api/guests")
def create_guest(body: GuestCreateIn, user: dict = Depends(auth.require_user)):
    """Add a customer to the address book. Core staff capability."""
    if not body.full_name.strip():
        raise HTTPException(400, "Name is required")
    with db.get_db() as conn:
        gid, is_new = _find_or_create_guest(
            conn, CheckinIn(**{k: v for k, v in body.dict().items() if k != "notes"}))
        if body.notes:
            conn.execute("UPDATE guests SET notes = ? WHERE id = ?", (body.notes, gid))
        row = dict(conn.execute("SELECT * FROM guests WHERE id = ?", (gid,)).fetchone())
    row["created"] = is_new
    return row


@app.put("/api/guests/{guest_id}")
def update_guest(guest_id: int, body: GuestIn, user: dict = Depends(auth.require_user)):
    with db.get_db() as conn:
        conn.execute(
            """UPDATE guests SET full_name=?, email=?, phone=?, id_number=?,
                 address=?, vehicle_reg=?, notes=?, updated_at=? WHERE id=?""",
            (body.full_name, body.email, body.phone, body.id_number,
             body.address, body.vehicle_reg, body.notes, _now(), guest_id),
        )
        return dict(conn.execute("SELECT * FROM guests WHERE id=?", (guest_id,)).fetchone())


@app.delete("/api/guests/{guest_id}")
def delete_guest(guest_id: int, user: dict = Depends(auth.require_perm("guests_delete"))):
    with db.get_db() as conn:
        conn.execute("DELETE FROM guests WHERE id = ?", (guest_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Stays / check-in management (admin)
# ---------------------------------------------------------------------------
class AssignIn(BaseModel):
    room_id: int
    check_in_at: Optional[str] = None
    check_out_at: str          # "how long" -> checkout date/time


class ManualStayIn(BaseModel):
    guest: GuestIn
    guest_id: Optional[int] = None   # picked from the existing-contacts list
    room_id: int
    check_in_at: Optional[str] = None
    check_out_at: str
    num_guests: Optional[int] = 1


def _room_or_409(conn, room_id: int):
    """Reject a check-in into a room that already has someone in it."""
    room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    occ = conn.execute(
        """SELECT g.full_name FROM stays s JOIN guests g ON g.id = s.guest_id
           WHERE s.room_id = ? AND s.status = 'checked_in'
           ORDER BY s.id DESC LIMIT 1""",
        (room_id,),
    ).fetchone()
    if occ:
        label = room["room_number"]
        if room["room_name"]:
            label += f" · {room['room_name']}"
        raise HTTPException(
            409,
            f"Room {label} is already occupied by {occ['full_name']} — "
            f"check them out first, or pick another room",
        )
    return room


def _stay_row(conn, sid):
    return conn.execute(
        """SELECT s.*, g.full_name, g.email, g.phone, g.id_number,
                  g.address, g.vehicle_reg,
                  r.room_number, r.room_name, r.room_code
           FROM stays s JOIN guests g ON g.id = s.guest_id
           LEFT JOIN rooms r ON r.id = s.room_id WHERE s.id = ?""",
        (sid,),
    ).fetchone()


@app.get("/api/stays")
def list_stays(status: Optional[str] = None, limit: Optional[int] = None,
               user: dict = Depends(auth.require_user)):
    q = """SELECT s.*, g.full_name, g.email, g.phone, g.id_number,
                  r.room_number, r.room_name
           FROM stays s JOIN guests g ON g.id = s.guest_id
           LEFT JOIN rooms r ON r.id = s.room_id"""
    params: tuple = ()
    if status:
        q += " WHERE s.status = ?"
        params = (status,)
    q += " ORDER BY s.created_at DESC"
    if limit:
        q += " LIMIT ?"
        params = (*params, int(limit))
    now = db.now_local()
    with db.get_db() as conn:
        rows = conn.execute(q, params).fetchall()
    return [notif.annotate_stay(dict(r), now) for r in rows]


@app.get("/api/stays/overdue")
def list_overdue(user: dict = Depends(auth.require_user)):
    """Guests who should already have checked out."""
    return notif.overdue_stays()


@app.post("/api/stays/{stay_id}/assign")
def assign_room(stay_id: int, body: AssignIn, user: dict = Depends(auth.require_user)):
    with db.get_db() as conn:
        st = conn.execute("SELECT * FROM stays WHERE id = ?", (stay_id,)).fetchone()
        if not st:
            raise HTTPException(404, "Stay not found")
        _room_or_409(conn, body.room_id)
        conn.execute(
            """UPDATE stays SET room_id=?, check_in_at=?, check_out_at=?,
                 status='checked_in' WHERE id=?""",
            (body.room_id, body.check_in_at or _now(), body.check_out_at, stay_id),
        )
        conn.execute("UPDATE rooms SET status='occupied' WHERE id=?", (body.room_id,))
        result = dict(_stay_row(conn, stay_id))
    ha_sync.notify_bg(result.get("room_number"), result.get("room_name"), True,
                      {"num_guests": result.get("num_guests"),
                       "due_out": result.get("check_out_at")})
    return result


@app.post("/api/stays")
def manual_stay(body: ManualStayIn, user: dict = Depends(auth.require_user)):
    with db.get_db() as conn:
        _room_or_409(conn, body.room_id)
        g = body.guest
        gid, _ = _find_or_create_guest(
            conn, CheckinIn(**{k: v for k, v in g.dict().items() if k != "notes"}),
            guest_id=body.guest_id,
        )
        cur = conn.execute(
            """INSERT INTO stays (guest_id, room_id, check_in_at, check_out_at,
                 num_guests, status, source, created_at)
               VALUES (?,?,?,?,?, 'checked_in', 'admin', ?)""",
            (gid, body.room_id, body.check_in_at or _now(), body.check_out_at,
             body.num_guests or 1, _now()),
        )
        conn.execute("UPDATE rooms SET status='occupied' WHERE id=?", (body.room_id,))
        result = dict(_stay_row(conn, cur.lastrowid))
    ha_sync.notify_bg(result.get("room_number"), result.get("room_name"), True,
                      {"num_guests": result.get("num_guests"),
                       "due_out": result.get("check_out_at")})
    return result


@app.post("/api/stays/{stay_id}/checkout")
def checkout_stay(stay_id: int, user: dict = Depends(auth.require_user)):
    now = db.now_local()
    with db.get_db() as conn:
        st = conn.execute("SELECT * FROM stays WHERE id = ?", (stay_id,)).fetchone()
        if not st:
            raise HTTPException(404, "Stay not found")
        conn.execute(
            "UPDATE stays SET status='checked_out', checked_out_at=? WHERE id=?",
            (now, stay_id),
        )
        room = None
        if st["room_id"]:
            conn.execute("UPDATE rooms SET status='available' WHERE id=?", (st["room_id"],))
            room = conn.execute(
                "SELECT room_number, room_name FROM rooms WHERE id=?", (st["room_id"],)
            ).fetchone()
        result = notif.annotate_stay(dict(_stay_row(conn, stay_id)), now)
    # room QR access dies with the stay; alerts for it are done shouting
    notif.clear_for_stay(stay_id)
    if room:
        ha_sync.notify_bg(room["room_number"], room["room_name"], False)
    return {"ok": True, "stay": result, "checked_out_at": now,
            "overstayed_minutes": result.get("overstayed_minutes", 0),
            "overstayed_text": result.get("overstayed_text", "")}


class ExtendIn(BaseModel):
    check_out_at: str


@app.post("/api/stays/{stay_id}/extend")
def extend_stay(stay_id: int, body: ExtendIn, user: dict = Depends(auth.require_user)):
    """Push the due-out time out — used straight from an overdue alert."""
    with db.get_db() as conn:
        if not conn.execute("SELECT 1 FROM stays WHERE id = ?", (stay_id,)).fetchone():
            raise HTTPException(404, "Stay not found")
        conn.execute(
            "UPDATE stays SET check_out_at=?, overdue_notified_at=NULL WHERE id=?",
            (body.check_out_at, stay_id),
        )
        result = notif.annotate_stay(dict(_stay_row(conn, stay_id)))
    notif.clear_for_stay(stay_id)
    return result


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
@app.get("/api/alerts")
def get_alerts(include_acked: bool = False, user: dict = Depends(auth.require_user)):
    return notif.list_alerts(include_acked=include_acked)


@app.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, user: dict = Depends(auth.require_user)):
    notif.ack_alert(alert_id)
    return {"ok": True}


@app.post("/api/alerts/ack-all")
def ack_all_alerts(user: dict = Depends(auth.require_user)):
    return {"ok": True, "cleared": notif.ack_all()}


@app.post("/api/alerts/scan")
def scan_alerts(user: dict = Depends(auth.require_user)):
    """Run the overdue sweep on demand (the watcher also does this every 60s)."""
    return notif.scan(force=True)


@app.post("/api/stays/{stay_id}/cancel")
def cancel_stay(stay_id: int, user: dict = Depends(auth.require_user)):
    with db.get_db() as conn:
        conn.execute("UPDATE stays SET status='cancelled' WHERE id=?", (stay_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Staff accounts (admin only)
# ---------------------------------------------------------------------------
class UserIn(BaseModel):
    username: str
    display_name: Optional[str] = ""
    password: Optional[str] = None
    role: Optional[str] = "staff"
    permissions: Optional[list] = None
    active: Optional[bool] = True


class UserUpdateIn(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[list] = None
    active: Optional[bool] = None


class UserPasswordIn(BaseModel):
    new_password: str


def _admin_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM users WHERE role = 'admin' AND active = 1"
    ).fetchone()["c"]


@app.get("/api/users")
def list_users(user: dict = Depends(auth.require_admin_role)):
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY role, username").fetchall()
    return {"users": [auth.public_user(dict(r)) for r in rows],
            "catalogue": auth.PERMISSIONS,
            "base_capabilities": auth.BASE_CAPABILITIES}


@app.post("/api/users")
def create_user(body: UserIn, user: dict = Depends(auth.require_admin_role)):
    uname = (body.username or "").strip().lower()
    if not uname:
        raise HTTPException(400, "Username is required")
    if not body.password or len(body.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    role = "admin" if body.role == "admin" else "staff"
    with db.get_db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE lower(username) = ?", (uname,)).fetchone():
            raise HTTPException(409, f"'{uname}' already exists")
        cur = conn.execute(
            """INSERT INTO users (username, display_name, password_hash, role,
                 permissions, active, created_at) VALUES (?,?,?,?,?,?,?)""",
            (uname, (body.display_name or "").strip(), db.hash_password(body.password),
             role, auth.clean_perms(body.permissions),
             1 if body.active is None else int(bool(body.active)), db.now_local()),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return auth.public_user(dict(row))


@app.put("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, user: dict = Depends(auth.require_admin_role)):
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        role = row["role"] if body.role is None else ("admin" if body.role == "admin" else "staff")
        active = row["active"] if body.active is None else int(bool(body.active))
        # never lock yourself out of the console
        if row["role"] == "admin" and (role != "admin" or not active) and _admin_count(conn) <= 1:
            raise HTTPException(400, "This is the only administrator — "
                                     "promote someone else first")
        if row["id"] == user["id"] and not active:
            raise HTTPException(400, "You can't disable your own account")
        conn.execute(
            """UPDATE users SET display_name=?, role=?, permissions=?, active=? WHERE id=?""",
            (row["display_name"] if body.display_name is None else body.display_name.strip(),
             role,
             row["permissions"] if body.permissions is None else auth.clean_perms(body.permissions),
             active, user_id),
        )
        out = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not active:
        db.drop_sessions_for_user(user_id)
    return auth.public_user(dict(out))


@app.post("/api/users/{user_id}/password")
def set_user_password(user_id: int, body: UserPasswordIn,
                      user: dict = Depends(auth.require_admin_role)):
    """Only an administrator can set any password — including their own."""
    if len(body.new_password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    with db.get_db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise HTTPException(404, "User not found")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (db.hash_password(body.new_password), user_id))
    if user_id != user["id"]:
        db.drop_sessions_for_user(user_id)   # force them to sign in again
    return {"ok": True}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(auth.require_admin_role)):
    if user_id == user["id"]:
        raise HTTPException(400, "You can't delete your own account")
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        if row["role"] == "admin" and _admin_count(conn) <= 1:
            raise HTTPException(400, "This is the only administrator")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.drop_sessions_for_user(user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Public room info (reached via per-room QR)  /api/room/{code}
# ---------------------------------------------------------------------------
@app.get("/api/room/{code}")
def public_room_info(code: str):
    with db.get_db() as conn:
        room = conn.execute("SELECT * FROM rooms WHERE room_code = ?", (code,)).fetchone()
        if not room:
            raise HTTPException(404, "Room not found")
        s = dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())
        occ = conn.execute(
            """SELECT g.full_name, s.check_in_at, s.check_out_at FROM stays s
               JOIN guests g ON g.id = s.guest_id
               WHERE s.room_id = ? AND s.status='checked_in'
               ORDER BY s.id DESC LIMIT 1""",
            (room["id"],),
        ).fetchone()
        last_out = conn.execute(
            """SELECT checked_out_at FROM stays
               WHERE room_id = ? AND status = 'checked_out'
               ORDER BY id DESC LIMIT 1""",
            (room["id"],),
        ).fetchone()

    # --- QR lockout -------------------------------------------------------
    # Once the guest is checked out the room QR stops handing out Wi-Fi,
    # the bar/restaurant menu and stay details. The printed code stays valid
    # for the next guest — it just goes dark while the room is empty.
    if not occ and s.get("room_lock_on_checkout", 1):
        grace = int(s.get("room_lock_grace_minutes") or 0)
        in_grace = False
        if grace > 0 and last_out and last_out["checked_out_at"]:
            since = db.minutes_between(last_out["checked_out_at"], db.now_local())
            in_grace = since is not None and since < grace
        if not in_grace:
            return {
                "locked": True,
                "room": {"room_number": room["room_number"],
                         "room_name": room["room_name"],
                         "floor": room["floor"]},
                "occupant": None,
                "hotel": {
                    "hotel_name": s["hotel_name"],
                    "address": s["address"],
                    "reception_phone": s["reception_phone"],
                    "emergency_number": s["emergency_number"],
                    "logo_url": _logo_url(s),
                    "locked_message": s.get("room_lock_message")
                    or "Your stay has ended. Please contact reception if you need anything.",
                },
            }

    return {
        "locked": False,
        "room": {
            "room_number": room["room_number"],
            "room_name": room["room_name"],
            "floor": room["floor"],
            "wifi_ssid": room["wifi_ssid"],
            "wifi_password": room["wifi_password"],
            "description": room["description"],
        },
        "occupant": dict(occ) if occ else None,
        "hotel": {
            "hotel_name": s["hotel_name"],
            "address": s["address"],
            "reception_phone": s["reception_phone"],
            "restaurant_name": s["restaurant_name"],
            "restaurant_phone": s["restaurant_phone"],
            "menu_url": s["menu_url"],
            "emergency_number": s["emergency_number"],
            "checkout_time": s["checkout_time"],
            "welcome_message": s["welcome_message"],
            "logo_url": _logo_url(s),
        },
    }


# ---------------------------------------------------------------------------
# Automation (smart-control bridge)
# ---------------------------------------------------------------------------
class AutomationIn(BaseModel):
    ha_enabled: Optional[bool] = None
    ha_url: Optional[str] = None
    ha_webhook_id: Optional[str] = None
    ha_room_prefix: Optional[str] = None
    ha_use_room_name: Optional[bool] = None
    ha_sync_minutes: Optional[int] = None
    ha_token: Optional[str] = None


AUTOMATION_FIELDS = (
    "ha_enabled", "ha_url", "ha_webhook_id", "ha_token",
    "ha_room_prefix", "ha_use_room_name", "ha_sync_minutes",
)


@app.get("/api/automation")
def get_automation(user: dict = Depends(auth.require_perm("automation"))):
    s = _settings_row()
    out = {k: s.get(k) for k in AUTOMATION_FIELDS}
    out["automation_name"] = ha_sync.AUTOMATION_NAME
    return out


@app.put("/api/automation")
def update_automation(body: AutomationIn, user: dict = Depends(auth.require_perm("automation"))):
    fields = {}
    for k in AUTOMATION_FIELDS:
        v = getattr(body, k)
        if v is not None:
            fields[k] = int(v) if isinstance(v, bool) else v
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.get_db() as conn:
            conn.execute(
                f"UPDATE settings SET {sets}, updated_at = ? WHERE id = 1",
                (*fields.values(), _now()),
            )
    return get_automation(user)


@app.post("/api/automation/test")
def test_automation(user: dict = Depends(auth.require_perm("automation"))):
    ok, msg = ha_sync.test_connection()
    return {"ok": ok, "message": msg}


@app.post("/api/automation/sync")
def sync_automation(user: dict = Depends(auth.require_perm("automation"))):
    ok, msg = ha_sync.full_sync()
    return {"ok": ok, "message": f"Synced all rooms to {ha_sync.AUTOMATION_NAME}"
            if ok else msg}


# public branding for the check-in page header
@app.get("/api/public/branding")
def public_branding():
    s = _settings_row()
    return {"hotel_name": s["hotel_name"], "welcome_message": s["welcome_message"],
            "address": s["address"], "logo_url": _logo_url(s)}


# ---------------------------------------------------------------------------
# QR endpoints
# ---------------------------------------------------------------------------
def _base_url(request: Request) -> str:
    s = _settings_row()
    if s.get("public_url"):
        return s["public_url"].rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/api/qr/checkin.png")
def qr_checkin(request: Request):
    url = f"{_base_url(request)}/checkin"
    return StreamingResponse(io.BytesIO(make_qr_png(url)), media_type="image/png")


@app.get("/api/qr/room/{code}.png")
def qr_room(code: str, request: Request):
    with db.get_db() as conn:
        if not conn.execute("SELECT 1 FROM rooms WHERE room_code = ?", (code,)).fetchone():
            raise HTTPException(404, "Room not found")
    url = f"{_base_url(request)}/room/{code}"
    return StreamingResponse(io.BytesIO(make_qr_png(url)), media_type="image/png")


# ---------------------------------------------------------------------------
# Version + updater
# ---------------------------------------------------------------------------
@app.get("/api/version")
def version():
    return {"version": updater.get_local_version(),
            "versions": updater.list_local_versions()}


@app.get("/api/update/check")
def update_check(user: dict = Depends(auth.require_perm("updates"))):
    return updater.check_updates()


@app.post("/api/update/apply")
def update_apply(user: dict = Depends(auth.require_perm("updates"))):
    return updater.request_update()


@app.get("/api/update/status")
def update_status(user: dict = Depends(auth.require_perm("updates"))):
    return updater.update_status()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": updater.get_local_version()}


# ---------------------------------------------------------------------------
# Frontend page routes
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse("/admin")


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(FRONTEND, "admin.html"))


@app.get("/checkin")
def checkin_page():
    return FileResponse(os.path.join(FRONTEND, "checkin.html"))


@app.get("/room/{code}")
def room_page(code: str):
    return FileResponse(os.path.join(FRONTEND, "room.html"))


# static assets (css/js)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
