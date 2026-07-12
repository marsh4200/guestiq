"""
GuestIQ -> Home Assistant automation bridge.
Fires the AR Smart Load Manager webhook when rooms are occupied/vacated,
plus a periodic full-state sync so a missed webhook always self-heals.

Config lives in the settings table (managed from the Automation tab):
  ha_enabled, ha_url, ha_webhook_id, ha_room_prefix, ha_use_room_name,
  ha_sync_minutes
"""
import logging
import threading
import time

import httpx

from . import database as db

log = logging.getLogger("guestiq.ha")

_TIMEOUT = 10
_RETRIES = 3
_RETRY_DELAY = 2  # seconds


def _cfg() -> dict:
    with db.get_db() as conn:
        row = conn.execute(
            """SELECT ha_enabled, ha_url, ha_webhook_id, ha_room_prefix,
                      ha_use_room_name, ha_sync_minutes
               FROM settings WHERE id = 1"""
        ).fetchone()
    return dict(row) if row else {}


def _endpoint(cfg: dict) -> str | None:
    url = (cfg.get("ha_url") or "").strip().rstrip("/")
    wid = (cfg.get("ha_webhook_id") or "").strip()
    if not url or not wid:
        return None
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return f"{url}/api/webhook/{wid}"


def enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or _cfg()
    return bool(cfg.get("ha_enabled")) and _endpoint(cfg) is not None


def _room_label(cfg: dict, room_number, room_name) -> str:
    if cfg.get("ha_use_room_name") and (room_name or "").strip():
        return str(room_name).strip()
    prefix = cfg.get("ha_room_prefix")
    if prefix is None:
        prefix = "Room "
    return f"{prefix}{room_number}"


def _post(payload: dict, cfg: dict | None = None) -> tuple[bool, str]:
    cfg = cfg or _cfg()
    endpoint = _endpoint(cfg)
    if not endpoint:
        return False, "HA URL or webhook ID not configured"
    last = ""
    for attempt in range(1, _RETRIES + 1):
        try:
            r = httpx.post(endpoint, json=payload, timeout=_TIMEOUT)
            if r.status_code < 300:
                log.info("HA sync ok: %s", payload)
                return True, "ok"
            last = f"HTTP {r.status_code}: {r.text[:150]}"
        except Exception as err:  # noqa: BLE001
            last = str(err)
        log.warning("HA sync attempt %s/%s failed: %s", attempt, _RETRIES, last)
        if attempt < _RETRIES:
            time.sleep(_RETRY_DELAY)
    log.error("HA sync FAILED: %s (%s) — full sync will heal this", payload, last)
    return False, last


# ---------------------------------------------------------------- public API
def notify_bg(room_number, room_name, occupied: bool) -> None:
    """Fire-and-forget occupancy event. Never blocks or fails the caller."""
    cfg = _cfg()
    if not enabled(cfg):
        return
    payload = {
        "room": _room_label(cfg, room_number, room_name),
        "occupied": bool(occupied),
    }
    threading.Thread(target=_post, args=(payload, cfg), daemon=True).start()


def occupancy_snapshot(cfg: dict | None = None) -> dict:
    cfg = cfg or _cfg()
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT room_number, room_name, status FROM rooms"
        ).fetchall()
    return {
        _room_label(cfg, r["room_number"], r["room_name"]): (r["status"] == "occupied")
        for r in rows
    }


def full_sync() -> tuple[bool, str]:
    """Push complete occupancy state for every room."""
    cfg = _cfg()
    if not enabled(cfg):
        return False, "Automation is disabled or not configured"
    snapshot = occupancy_snapshot(cfg)
    if not snapshot:
        return False, "No rooms configured in GuestIQ yet"
    return _post({"rooms": snapshot}, cfg)


def test_connection() -> tuple[bool, str]:
    """Used by the Test button: pushes a full sync and reports the result."""
    cfg = _cfg()
    if not _endpoint(cfg):
        return False, "Enter the HA URL and webhook ID first"
    snapshot = occupancy_snapshot(cfg)
    ok, msg = _post({"rooms": snapshot}, cfg)
    if ok:
        return True, f"Connected — synced {len(snapshot)} room(s) to Home Assistant"
    return False, msg


# ---------------------------------------------------------------- background
_started = False


def start_periodic() -> None:
    """Start the self-healing full-sync loop. Safe to call once at startup."""
    global _started
    if _started:
        return
    _started = True

    def _loop() -> None:
        log.info("HA periodic sync loop started")
        while True:
            sleep_s = 900
            try:
                cfg = _cfg()
                minutes = int(cfg.get("ha_sync_minutes") or 15)
                if enabled(cfg) and minutes > 0:
                    full_sync()
                sleep_s = max(60, minutes * 60) if minutes > 0 else 900
            except Exception:  # noqa: BLE001 — the loop must never die
                log.exception("HA periodic sync failed")
            time.sleep(sleep_s)

    threading.Thread(target=_loop, daemon=True, name="guestiq-ha-sync").start()
