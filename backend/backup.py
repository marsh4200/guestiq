"""
GuestIQ - backup & restore.

A backup is a single .zip holding:
  guestiq-backup.json   every table: settings, rooms, guests, stays, users, alerts
  branding/<logo>       the uploaded property logo, if there is one

Restoring is version-tolerant: columns that no longer exist are ignored and
columns added since the backup fall back to their schema defaults, so a backup
taken on an older GuestIQ still restores cleanly onto a newer one.
"""
import datetime as dt
import io
import json
import logging
import os
import sqlite3
import threading
import time
import zipfile

from . import database as db

log = logging.getLogger("guestiq.backup")

MANIFEST = "guestiq-backup.json"
BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")
LOGO_DIR = os.path.join(db.DATA_DIR, "branding")

# Order matters on restore: parents before children.
TABLES = ["settings", "users", "rooms", "guests", "stays", "alerts"]
NEVER_RESTORED = ["sessions"]


def _app_version() -> str:
    try:
        from . import updater
        return updater.get_local_version()
    except Exception:  # noqa: BLE001
        return "unknown"


def _columns(conn, table) -> list:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def export_bytes() -> bytes:
    payload = {
        "app": "GuestIQ",
        "format": 1,
        "version": _app_version(),
        "created_at": db.now_local(),
        "tables": {},
        "counts": {},
    }
    with db.get_db() as conn:
        for t in TABLES:
            try:
                rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
            except sqlite3.OperationalError:
                rows = []
            payload["tables"][t] = rows
            payload["counts"][t] = len(rows)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(payload, indent=1, ensure_ascii=False))
        if os.path.isdir(LOGO_DIR):
            for name in os.listdir(LOGO_DIR):
                path = os.path.join(LOGO_DIR, name)
                if os.path.isfile(path):
                    z.write(path, f"branding/{name}")
    return buf.getvalue()


def summarise(data: bytes) -> dict:
    """Read a backup's manifest without applying anything."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            meta = json.loads(z.read(MANIFEST).decode())
    except (KeyError, zipfile.BadZipFile, ValueError):
        raise ValueError("That isn't a GuestIQ backup file")
    if meta.get("app") != "GuestIQ":
        raise ValueError("That isn't a GuestIQ backup file")
    return {
        "version": meta.get("version"),
        "created_at": meta.get("created_at"),
        "counts": meta.get("counts") or {},
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def restore_bytes(data: bytes, include_users: bool = True) -> dict:
    """Replace the contents of the database with the backup.

    A safety snapshot of the current data is written to data/backups/ first,
    so restoring the wrong file is always recoverable.
    """
    summary = summarise(data)          # validates before anything is touched
    safety = save_to_disk(prefix="pre-restore")

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        meta = json.loads(z.read(MANIFEST).decode())
        logo_names = [n for n in z.namelist()
                      if n.startswith("branding/") and not n.endswith("/")]
        logo_blobs = {os.path.basename(n): z.read(n) for n in logo_names}

    tables = meta.get("tables") or {}
    wanted = [t for t in TABLES if t in tables]
    if not include_users and "users" in wanted:
        wanted.remove("users")

    restored = {}
    conn = sqlite3.connect(db.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=OFF;")
        conn.execute("BEGIN")
        for t in wanted:
            cols = _columns(conn, t)
            if not cols:
                continue
            conn.execute(f"DELETE FROM {t}")
            usable = []
            for row in (tables.get(t) or []):
                keep = {k: v for k, v in row.items() if k in cols}
                if keep:
                    usable.append(keep)
            for keep in usable:
                names = ", ".join(keep)
                marks = ", ".join("?" for _ in keep)
                conn.execute(f"INSERT INTO {t} ({names}) VALUES ({marks})",
                             tuple(keep.values()))
            restored[t] = len(usable)
        for t in NEVER_RESTORED:
            conn.execute(f"DELETE FROM {t}")     # everyone signs in again
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        log.exception("Restore failed - database left untouched")
        raise
    conn.close()

    if logo_blobs:
        os.makedirs(LOGO_DIR, exist_ok=True)
        for old in os.listdir(LOGO_DIR):
            try:
                os.remove(os.path.join(LOGO_DIR, old))
            except OSError:
                pass
        for name, blob in logo_blobs.items():
            with open(os.path.join(LOGO_DIR, name), "wb") as fh:
                fh.write(blob)

    db.init_db()                 # re-apply migrations / re-seed if needed
    db.tz_offset_minutes(force=True)
    log.info("Restore complete: %s", restored)
    return {"restored": restored, "backup": summary, "safety_copy": safety}


# ---------------------------------------------------------------------------
# Server-side snapshots
# ---------------------------------------------------------------------------
def save_to_disk(prefix: str = "backup") -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    name = f"guestiq-{prefix}-{stamp}.zip"
    with open(os.path.join(BACKUP_DIR, name), "wb") as fh:
        fh.write(export_bytes())
    try:
        with db.get_db() as conn:
            conn.execute("UPDATE settings SET last_backup_at = ? WHERE id = 1",
                         (db.now_local(),))
    except sqlite3.OperationalError:
        pass
    return name


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "")
    if not base.endswith(".zip") or "/" in base or "\\" in base:
        raise ValueError("Unknown backup file")
    return base


def list_backups() -> list:
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for name in os.listdir(BACKUP_DIR):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        kind = "auto" if "-auto-" in name else (
            "pre-restore" if "-pre-restore-" in name else "manual")
        item = {"name": name, "size": st.st_size, "kind": kind,
                "created_at": dt.datetime.fromtimestamp(st.st_mtime)
                                .isoformat(timespec="seconds")}
        try:
            with open(path, "rb") as fh:
                item["counts"] = summarise(fh.read()).get("counts", {})
        except Exception:  # noqa: BLE001
            item["counts"] = {}
        out.append(item)
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def read_backup(name: str) -> bytes:
    path = os.path.join(BACKUP_DIR, _safe_name(name))
    if not os.path.exists(path):
        raise ValueError("Unknown backup file")
    with open(path, "rb") as fh:
        return fh.read()


def delete_backup(name: str) -> None:
    path = os.path.join(BACKUP_DIR, _safe_name(name))
    if os.path.exists(path):
        os.remove(path)


def prune(keep: int) -> int:
    """Keep the newest `keep` scheduled backups. Manual downloads and
    pre-restore safety copies are never pruned."""
    if keep <= 0:
        return 0
    scheduled = [b for b in list_backups() if b["kind"] == "auto"]
    removed = 0
    for b in scheduled[keep:]:
        try:
            delete_backup(b["name"])
            removed += 1
        except (OSError, ValueError):
            pass
    return removed


# ---------------------------------------------------------------------------
# Daily scheduler
# ---------------------------------------------------------------------------
_started = False


def _cfg() -> dict:
    try:
        with db.get_db() as conn:
            row = conn.execute(
                "SELECT auto_backup_enabled, auto_backup_keep, last_backup_at "
                "FROM settings WHERE id = 1"
            ).fetchone()
        return dict(row) if row else {}
    except sqlite3.OperationalError:
        return {}


def run_scheduled(force: bool = False) -> dict:
    cfg = _cfg()
    if not force and not cfg.get("auto_backup_enabled"):
        return {"made": False, "reason": "Automatic backups are switched off"}
    last = db.parse_ts(cfg.get("last_backup_at"))
    now = db.parse_ts(db.now_local())
    if not force and last and now and (now - last) < dt.timedelta(hours=23):
        return {"made": False, "reason": "Already backed up in the last 24 hours"}
    name = save_to_disk(prefix="auto")
    pruned = prune(int(cfg.get("auto_backup_keep") or 7))
    return {"made": True, "name": name, "pruned": pruned}


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True

    def _loop() -> None:
        log.info("Backup scheduler started")
        time.sleep(30)
        while True:
            try:
                run_scheduled()
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Scheduled backup failed")
            time.sleep(3600)

    threading.Thread(target=_loop, daemon=True, name="guestiq-backup").start()
