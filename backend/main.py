"""
GuestIQ - hotel guest check-in + in-room info system.
FastAPI + SQLite. Serves an admin dashboard and two QR-driven guest flows:
  1. /checkin        -> guest self check-in form (arrival QR)
  2. /room/{code}    -> in-room info: wifi, restaurant, menu, etc. (per-room QR)
"""
import os
import datetime as dt
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header, Depends
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")

app = FastAPI(title="GuestIQ", version=updater.get_local_version())


@app.on_event("startup")
def _startup():
    db.init_db()
    ha_sync.start_periodic()
    notif.start_watcher()


def _now():
    """Local wall-clock, matching the <input type=datetime-local> values the
    admin UI sends. See database.tz_offset_minutes."""
    return db.now_local()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_admin(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
):
    token = x_auth_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not db.session_valid(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token


class LoginIn(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginIn):
    with db.get_db() as conn:
        row = conn.execute("SELECT admin_password FROM settings WHERE id = 1").fetchone()
    if not row or not db.verify_password(body.password, row["admin_password"]):
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": db.create_session()}


@app.post("/api/logout")
def logout(token: str = Depends(require_admin)):
    db.destroy_session(token)
    return {"ok": True}


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


def _settings_row():
    with db.get_db() as conn:
        return dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())


@app.get("/api/settings")
def get_settings(token: str = Depends(require_admin)):
    s = _settings_row()
    s.pop("admin_password", None)
    return s


@app.put("/api/settings")
def update_settings(body: SettingsIn, token: str = Depends(require_admin)):
    fields = {k: (int(v) if isinstance(v, bool) else v)
              for k, v in body.dict().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.get_db() as conn:
            conn.execute(
                f"UPDATE settings SET {sets}, updated_at = ? WHERE id = 1",
                (*fields.values(), db.now_local()),
            )
        db.tz_offset_minutes(force=True)  # drop the cached offset
    return get_settings(token)


@app.post("/api/settings/password")
def change_password(body: PasswordIn, token: str = Depends(require_admin)):
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password too short")
    with db.get_db() as conn:
        conn.execute(
            "UPDATE settings SET admin_password = ?, updated_at = ? WHERE id = 1",
            (db.hash_password(body.new_password), _now()),
        )
    return {"ok": True}


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
def list_rooms(token: str = Depends(require_admin)):
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


@app.post("/api/rooms")
def create_room(body: RoomIn, token: str = Depends(require_admin)):
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
def update_room(room_id: int, body: RoomIn, token: str = Depends(require_admin)):
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
def delete_room(room_id: int, token: str = Depends(require_admin)):
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


def _find_or_create_guest(conn, body: CheckinIn):
    """Save guest for future: match on id_number, then email, then phone."""
    row = None
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
        conn.execute(
            """UPDATE guests SET full_name=?, email=?, phone=?, id_number=?,
                 address=?, vehicle_reg=?, updated_at=? WHERE id=?""",
            (body.full_name, body.email, body.phone, body.id_number,
             body.address, body.vehicle_reg, _now(), gid),
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


@app.get("/api/guests")
def list_guests(q: Optional[str] = None, token: str = Depends(require_admin)):
    with db.get_db() as conn:
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                """SELECT * FROM guests WHERE full_name LIKE ? OR email LIKE ?
                   OR phone LIKE ? OR id_number LIKE ? ORDER BY updated_at DESC""",
                (like, like, like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM guests ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


@app.put("/api/guests/{guest_id}")
def update_guest(guest_id: int, body: GuestIn, token: str = Depends(require_admin)):
    with db.get_db() as conn:
        conn.execute(
            """UPDATE guests SET full_name=?, email=?, phone=?, id_number=?,
                 address=?, vehicle_reg=?, notes=?, updated_at=? WHERE id=?""",
            (body.full_name, body.email, body.phone, body.id_number,
             body.address, body.vehicle_reg, body.notes, _now(), guest_id),
        )
        return dict(conn.execute("SELECT * FROM guests WHERE id=?", (guest_id,)).fetchone())


@app.delete("/api/guests/{guest_id}")
def delete_guest(guest_id: int, token: str = Depends(require_admin)):
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
    room_id: int
    check_in_at: Optional[str] = None
    check_out_at: str
    num_guests: Optional[int] = 1


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
               token: str = Depends(require_admin)):
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
def list_overdue(token: str = Depends(require_admin)):
    """Guests who should already have checked out."""
    return notif.overdue_stays()


@app.post("/api/stays/{stay_id}/assign")
def assign_room(stay_id: int, body: AssignIn, token: str = Depends(require_admin)):
    with db.get_db() as conn:
        st = conn.execute("SELECT * FROM stays WHERE id = ?", (stay_id,)).fetchone()
        if not st:
            raise HTTPException(404, "Stay not found")
        if not conn.execute("SELECT 1 FROM rooms WHERE id = ?", (body.room_id,)).fetchone():
            raise HTTPException(404, "Room not found")
        conn.execute(
            """UPDATE stays SET room_id=?, check_in_at=?, check_out_at=?,
                 status='checked_in' WHERE id=?""",
            (body.room_id, body.check_in_at or _now(), body.check_out_at, stay_id),
        )
        conn.execute("UPDATE rooms SET status='occupied' WHERE id=?", (body.room_id,))
        result = dict(_stay_row(conn, stay_id))
    ha_sync.notify_bg(result.get("room_number"), result.get("room_name"), True)
    return result


@app.post("/api/stays")
def manual_stay(body: ManualStayIn, token: str = Depends(require_admin)):
    with db.get_db() as conn:
        g = body.guest
        gid, _ = _find_or_create_guest(conn, CheckinIn(**g.dict()))
        cur = conn.execute(
            """INSERT INTO stays (guest_id, room_id, check_in_at, check_out_at,
                 num_guests, status, source, created_at)
               VALUES (?,?,?,?,?, 'checked_in', 'admin', ?)""",
            (gid, body.room_id, body.check_in_at or _now(), body.check_out_at,
             body.num_guests or 1, _now()),
        )
        conn.execute("UPDATE rooms SET status='occupied' WHERE id=?", (body.room_id,))
        result = dict(_stay_row(conn, cur.lastrowid))
    ha_sync.notify_bg(result.get("room_number"), result.get("room_name"), True)
    return result


@app.post("/api/stays/{stay_id}/checkout")
def checkout_stay(stay_id: int, token: str = Depends(require_admin)):
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
def extend_stay(stay_id: int, body: ExtendIn, token: str = Depends(require_admin)):
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
def get_alerts(include_acked: bool = False, token: str = Depends(require_admin)):
    return notif.list_alerts(include_acked=include_acked)


@app.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, token: str = Depends(require_admin)):
    notif.ack_alert(alert_id)
    return {"ok": True}


@app.post("/api/alerts/ack-all")
def ack_all_alerts(token: str = Depends(require_admin)):
    return {"ok": True, "cleared": notif.ack_all()}


@app.post("/api/alerts/scan")
def scan_alerts(token: str = Depends(require_admin)):
    """Run the overdue sweep on demand (the watcher also does this every 60s)."""
    return notif.scan(force=True)


@app.post("/api/stays/{stay_id}/cancel")
def cancel_stay(stay_id: int, token: str = Depends(require_admin)):
    with db.get_db() as conn:
        conn.execute("UPDATE stays SET status='cancelled' WHERE id=?", (stay_id,))
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
        },
    }


# ---------------------------------------------------------------------------
# Automation (Home Assistant bridge)
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
def get_automation(token: str = Depends(require_admin)):
    s = _settings_row()
    return {k: s.get(k) for k in AUTOMATION_FIELDS}


@app.put("/api/automation")
def update_automation(body: AutomationIn, token: str = Depends(require_admin)):
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
    return get_automation(token)


@app.post("/api/automation/test")
def test_automation(token: str = Depends(require_admin)):
    ok, msg = ha_sync.test_connection()
    return {"ok": ok, "message": msg}


@app.post("/api/automation/sync")
def sync_automation(token: str = Depends(require_admin)):
    ok, msg = ha_sync.full_sync()
    return {"ok": ok, "message": "Synced all rooms to Home Assistant" if ok else msg}


# public branding for the check-in page header
@app.get("/api/public/branding")
def public_branding():
    s = _settings_row()
    return {"hotel_name": s["hotel_name"], "welcome_message": s["welcome_message"],
            "address": s["address"]}


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
def update_check(token: str = Depends(require_admin)):
    return updater.check_updates()


@app.post("/api/update/apply")
def update_apply(token: str = Depends(require_admin)):
    return updater.request_update()


@app.get("/api/update/status")
def update_status(token: str = Depends(require_admin)):
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
