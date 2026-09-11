"""
GuestIQ - overdue checkout alerts.

A stay is "overdue" when it is still checked_in and the wall clock has passed
check_out_at (plus a grace period). The watcher thread raises an in-app alert,
pushes a notification to the automation hub, and re-nags on an interval
until reception either checks the guest out or extends the stay.
"""
import datetime as dt
import logging
import threading
import time

from . import database as db
from . import ha_sync

log = logging.getLogger("guestiq.alerts")

SCAN_SECONDS = 60


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def _cfg() -> dict:
    with db.get_db() as conn:
        row = conn.execute(
            """SELECT overdue_alerts_enabled, overdue_grace_minutes,
                      overdue_repeat_hours, hotel_name
               FROM settings WHERE id = 1"""
        ).fetchone()
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Overdue maths
# ---------------------------------------------------------------------------
def minutes_over(check_out_at: str, now: str | None = None):
    """Minutes past the due-out time. Negative = still has time. None = no due date."""
    return db.minutes_between(check_out_at, now or db.now_local())


def humanise(minutes) -> str:
    if minutes is None:
        return ""
    minutes = int(abs(minutes))
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def annotate_stay(row: dict, now: str | None = None) -> dict:
    """Add overdue / overstay fields to a stay dict for the API."""
    now = now or db.now_local()
    s = dict(row)
    over = None
    if s.get("status") == "checked_in" and s.get("check_out_at"):
        over = minutes_over(s["check_out_at"], now)
        s["overdue"] = bool(over is not None and over > 0)
        s["minutes_over"] = over if over and over > 0 else 0
    elif s.get("status") == "checked_out" and s.get("check_out_at") and s.get("checked_out_at"):
        over = db.minutes_between(s["check_out_at"], s["checked_out_at"])
        s["overdue"] = False
        s["minutes_over"] = 0
        s["overstayed_minutes"] = over if over and over > 0 else 0
        s["overstayed_text"] = humanise(over) if over and over > 0 else ""
    else:
        s["overdue"] = False
        s["minutes_over"] = 0
    if s.get("minutes_over"):
        s["overdue_text"] = humanise(s["minutes_over"])
    # stay length (checked in -> actual/expected out)
    end = s.get("checked_out_at") or s.get("check_out_at")
    if s.get("check_in_at") and end:
        mins = db.minutes_between(s["check_in_at"], end)
        if mins is not None and mins > 0:
            s["duration_minutes"] = mins
            s["duration_text"] = humanise(mins)
    return s


# ---------------------------------------------------------------------------
# Alert store
# ---------------------------------------------------------------------------
def create_alert(kind: str, title: str, message: str, stay_id=None,
                 room_id=None, severity: str = "warn") -> int:
    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO alerts (kind, stay_id, room_id, title, message,
                 severity, created_at) VALUES (?,?,?,?,?,?,?)""",
            (kind, stay_id, room_id, title, message, severity, db.now_local()),
        )
        return cur.lastrowid


def list_alerts(include_acked: bool = False, limit: int = 50) -> list[dict]:
    q = """SELECT a.*, g.full_name, r.room_number, r.room_name
           FROM alerts a
           LEFT JOIN stays s ON s.id = a.stay_id
           LEFT JOIN guests g ON g.id = s.guest_id
           LEFT JOIN rooms r ON r.id = a.room_id"""
    if not include_acked:
        q += " WHERE a.acknowledged_at IS NULL"
    q += " ORDER BY a.id DESC LIMIT ?"
    with db.get_db() as conn:
        return [dict(r) for r in conn.execute(q, (limit,)).fetchall()]


def ack_alert(alert_id: int) -> None:
    with db.get_db() as conn:
        conn.execute(
            "UPDATE alerts SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
            (db.now_local(), alert_id),
        )


def ack_all() -> int:
    with db.get_db() as conn:
        cur = conn.execute(
            "UPDATE alerts SET acknowledged_at = ? WHERE acknowledged_at IS NULL",
            (db.now_local(),),
        )
        return cur.rowcount


def clear_for_stay(stay_id: int) -> None:
    """Called on checkout / extend so the alert stops shouting."""
    with db.get_db() as conn:
        conn.execute(
            """UPDATE alerts SET acknowledged_at = ?
               WHERE stay_id = ? AND acknowledged_at IS NULL""",
            (db.now_local(), stay_id),
        )
        conn.execute("UPDATE stays SET overdue_notified_at = NULL WHERE id = ?", (stay_id,))


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
def overdue_stays(now: str | None = None) -> list[dict]:
    now = now or db.now_local()
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT s.*, g.full_name, g.phone, r.room_number, r.room_name
               FROM stays s JOIN guests g ON g.id = s.guest_id
               LEFT JOIN rooms r ON r.id = s.room_id
               WHERE s.status = 'checked_in' AND IFNULL(s.check_out_at,'') != ''"""
        ).fetchall()
    out = []
    for r in rows:
        d = annotate_stay(dict(r), now)
        if d.get("overdue"):
            out.append(d)
    return out


def scan(force: bool = False) -> dict:
    """Find overdue stays, raise alerts, notify the hub. Returns a summary."""
    cfg = _cfg()
    if not force and not cfg.get("overdue_alerts_enabled", 1):
        return {"overdue": 0, "notified": 0, "enabled": False}

    grace = int(cfg.get("overdue_grace_minutes") or 0)
    repeat_h = int(cfg.get("overdue_repeat_hours") or 0)
    hotel = cfg.get("hotel_name") or "GuestIQ"
    now = db.now_local()
    now_dt = db.parse_ts(now)

    notified = 0
    stays = overdue_stays(now)
    for s in stays:
        if s["minutes_over"] < grace:
            continue
        last = db.parse_ts(s.get("overdue_notified_at"))
        if last and repeat_h > 0 and now_dt and (now_dt - last) < dt.timedelta(hours=repeat_h):
            continue
        if last and repeat_h <= 0:
            continue  # notify once only

        room = s.get("room_number") or "—"
        if s.get("room_name"):
            room = f"{room} · {s['room_name']}"
        title = f"Overdue checkout — Room {s.get('room_number') or '?'}"
        msg = (
            f"{s.get('full_name') or 'Guest'} in {room} was due out at "
            f"{(s.get('check_out_at') or '').replace('T', ' ')[:16]} — "
            f"{humanise(s['minutes_over'])} overdue."
        )
        create_alert("overdue_checkout", title, msg, stay_id=s["id"],
                     room_id=s.get("room_id"), severity="alert")
        ha_sync.notify_message_bg(
            f"{hotel}: {title}", msg,
            data={
                "event": "overdue_checkout",
                "stay_id": s["id"],
                "guest": s.get("full_name"),
                "room": s.get("room_number"),
                "room_name": s.get("room_name"),
                "due_out": s.get("check_out_at"),
                "minutes_over": s["minutes_over"],
            },
        )
        with db.get_db() as conn:
            conn.execute("UPDATE stays SET overdue_notified_at = ? WHERE id = ?", (now, s["id"]))
        notified += 1
        log.info("Overdue checkout alert: stay=%s %s", s["id"], msg)

    return {"overdue": len(stays), "notified": notified, "enabled": True}


# ---------------------------------------------------------------------------
# Background watcher
# ---------------------------------------------------------------------------
_started = False


def start_watcher() -> None:
    global _started
    if _started:
        return
    _started = True

    def _loop() -> None:
        log.info("Overdue checkout watcher started (%ss interval)", SCAN_SECONDS)
        time.sleep(10)  # let startup settle
        while True:
            try:
                scan()
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Overdue scan failed")
            time.sleep(SCAN_SECONDS)

    threading.Thread(target=_loop, daemon=True, name="guestiq-overdue").start()
