"""
GuestIQ -> automation hub bridge.
Fires the load-manager webhook when rooms are occupied/vacated, plus a
periodic full-state sync so a missed webhook always self-heals.

The hub is never named in anything the operator sees: every message returned
to the UI uses AUTOMATION_NAME (override with GUESTIQ_AUTOMATION_NAME).

Config lives in the settings table (managed from the Automation tab):
  ha_enabled, ha_url, ha_webhook_id, ha_room_prefix, ha_use_room_name,
  ha_sync_minutes
"""
import logging
import os
import threading
import time

import httpx

from . import database as db

log = logging.getLogger("guestiq.ha")

# Operator-facing name for the automation back end.
AUTOMATION_NAME = os.environ.get("GUESTIQ_AUTOMATION_NAME", "AR Smart automation")

_TIMEOUT = 10
_RETRIES = 3
_RETRY_DELAY = 2  # seconds


def _cfg() -> dict:
    with db.get_db() as conn:
        row = conn.execute(
            """SELECT ha_enabled, ha_url, ha_webhook_id, ha_room_prefix,
                      ha_use_room_name, ha_sync_minutes, ha_token
               FROM settings WHERE id = 1"""
        ).fetchone()
    return dict(row) if row else {}


def _base_url(cfg: dict) -> str | None:
    url = (cfg.get("ha_url") or "").strip().rstrip("/")
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _token(cfg: dict) -> str:
    return (cfg.get("ha_token") or "").strip()


def _endpoint(cfg: dict) -> str | None:
    url = _base_url(cfg)
    wid = (cfg.get("ha_webhook_id") or "").strip()
    if not url or not wid:
        return None
    return f"{url}/api/webhook/{wid}"


def enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or _cfg()
    if not cfg.get("ha_enabled"):
        return False
    # Token mode (preferred) or webhook mode
    return bool(_base_url(cfg) and _token(cfg)) or _endpoint(cfg) is not None


def _room_label(cfg: dict, room_number, room_name) -> str:
    if cfg.get("ha_use_room_name") and (room_name or "").strip():
        return str(room_name).strip()
    prefix = cfg.get("ha_room_prefix")
    if prefix is None:
        prefix = "Room "
    return f"{prefix}{room_number}"


def _request(url: str, payload: dict, headers: dict | None) -> tuple[bool, str]:
    last = ""
    for attempt in range(1, _RETRIES + 1):
        try:
            r = httpx.post(url, json=payload, headers=headers or {}, timeout=_TIMEOUT)
            if r.status_code < 300:
                return True, "ok"
            if r.status_code == 401:
                return False, f"HTTP 401 — access token rejected by {AUTOMATION_NAME}"
            last = f"HTTP {r.status_code}: {r.text[:150]}"
        except Exception as err:  # noqa: BLE001
            last = str(err)
        log.warning("HA sync attempt %s/%s failed: %s", attempt, _RETRIES, last)
        if attempt < _RETRIES:
            time.sleep(_RETRY_DELAY)
    log.error("HA sync FAILED: %s (%s)", payload, last)
    return False, last


def _send_occupancy(cfg: dict, room_label: str, occupied: bool,
                    extra: dict | None = None) -> tuple[bool, str]:
    """Token mode: call the set_occupancy service on the hub's REST API.
    Webhook mode (no token): post to the webhook."""
    payload = {"room": room_label, "occupied": bool(occupied)}
    payload.update(extra or {})
    base = _base_url(cfg)
    token = _token(cfg)
    if base and token:
        return _request(
            f"{base}/api/services/ar_smart_loadmanager/set_occupancy",
            payload,
            {"Authorization": f"Bearer {token}"},
        )
    endpoint = _endpoint(cfg)
    if not endpoint:
        return False, "Configure the hub URL plus a token (or webhook ID)"
    return _request(endpoint, payload, None)


def _send_message(cfg: dict, title: str, message: str, data: dict | None) -> tuple[bool, str]:
    """Raise a persistent notification on the hub (token mode), else post to
    the webhook. Used for overdue-checkout alerts."""
    base = _base_url(cfg)
    token = _token(cfg)
    if base and token:
        return _request(
            f"{base}/api/services/persistent_notification/create",
            {"title": title, "message": message,
             "notification_id": f"guestiq_{(data or {}).get('event','alert')}_"
                                f"{(data or {}).get('stay_id','x')}"},
            {"Authorization": f"Bearer {token}"},
        )
    endpoint = _endpoint(cfg)
    if not endpoint:
        return False, f"{AUTOMATION_NAME} is not configured"
    payload = {"title": title, "message": message}
    payload.update(data or {})
    return _request(endpoint, payload, None)


# ---------------------------------------------------------------- public API
def notify_message_bg(title: str, message: str, data: dict | None = None) -> None:
    """Fire-and-forget alert to the automation hub. Never blocks the caller."""
    cfg = _cfg()
    if not enabled(cfg):
        return
    threading.Thread(
        target=_send_message, args=(cfg, title, message, data), daemon=True
    ).start()


def notify_bg(room_number, room_name, occupied: bool, extra: dict | None = None) -> None:
    """Fire-and-forget occupancy event. Never blocks or fails the caller.

    The payload carries more than on/off so hub automations can drive whatever
    is wired to the room — geyser, lights, TV, air-con, anything:
        room, occupied, num_guests, due_out, event
    """
    cfg = _cfg()
    if not enabled(cfg):
        return
    label = _room_label(cfg, room_number, room_name)
    body = {"event": "occupied" if occupied else "vacated"}
    body.update(extra or {})
    threading.Thread(
        target=_send_occupancy, args=(cfg, label, bool(occupied), body), daemon=True
    ).start()


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
    if _base_url(cfg) and _token(cfg):
        failures = []
        for label, occ in snapshot.items():
            ok, msg = _send_occupancy(cfg, label, occ)
            if not ok:
                failures.append(f"{label}: {msg}")
        if failures:
            return False, "; ".join(failures[:3])
        return True, "ok"
    return _request(_endpoint(cfg), {"rooms": snapshot}, None)


def test_connection() -> tuple[bool, str]:
    """Used by the Test button: verifies auth, then pushes a full sync."""
    cfg = _cfg()
    base = _base_url(cfg)
    token = _token(cfg)
    if not base:
        return False, "Enter the automation hub URL first"
    if token:
        try:
            r = httpx.get(
                f"{base}/api/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT,
            )
            if r.status_code == 401:
                return False, "Token rejected (401) — generate a new access token on the hub"
            if r.status_code >= 300:
                return False, f"The hub answered HTTP {r.status_code}"
        except Exception as err:  # noqa: BLE001
            return False, f"Cannot reach {AUTOMATION_NAME}: {err}"
    elif not _endpoint(cfg):
        return False, "Enter an access token (or a webhook ID) first"
    snapshot = occupancy_snapshot(cfg)
    if not snapshot:
        return True, f"Connected to {AUTOMATION_NAME} — add rooms in GuestIQ to sync them"
    ok, msg = full_sync() if enabled(cfg) else (False, "Tick 'Enable automation sync' first")
    if ok:
        return True, f"Connected — synced {len(snapshot)} room(s) to {AUTOMATION_NAME}"
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
