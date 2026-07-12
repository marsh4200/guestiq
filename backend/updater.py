"""
GuestIQ self-updater.

- Local version comes from the VERSION file at the repo root.
- Remote version is fetched from raw.githubusercontent.com.
- Applying an update writes a flag file into data/ which the host-side
  watcher (guestiq-watch.sh / systemd) picks up to run:  git pull + docker rebuild.
  This avoids fragile docker-in-docker while keeping a one-click "Update now".
"""
import os
import json
import urllib.request

REPO = os.environ.get("GUESTIQ_REPO", "marsh4200/guestiq")
BRANCH = os.environ.get("GUESTIQ_BRANCH", "main")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "VERSION")
VERSIONS_DIR = os.path.join(ROOT, "versions")
DATA_DIR = os.environ.get("GUESTIQ_DATA", os.path.join(os.getcwd(), "data"))
UPDATE_FLAG = os.path.join(DATA_DIR, ".update_requested")


def get_local_version() -> str:
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


def _ver_tuple(v: str):
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def get_remote_version(timeout: int = 8):
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GuestIQ-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def get_local_changelog(version: str):
    path = os.path.join(VERSIONS_DIR, f"{version}.md")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


def get_remote_changelog(version: str, timeout: int = 8):
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/versions/{version}.md"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GuestIQ-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip()
    except Exception:
        return ""


def list_local_versions():
    out = []
    if os.path.isdir(VERSIONS_DIR):
        for f in os.listdir(VERSIONS_DIR):
            if f.endswith(".md"):
                out.append(f[:-3])
    out.sort(key=_ver_tuple, reverse=True)
    return out


def check_updates():
    local = get_local_version()
    remote = get_remote_version()
    available = bool(remote) and _ver_tuple(remote) > _ver_tuple(local)
    return {
        "local": local,
        "remote": remote,
        "update_available": available,
        "remote_changelog": get_remote_changelog(remote) if available else "",
        "repo": REPO,
        "branch": BRANCH,
    }


def update_status():
    """Live status for the update progress UI.

    flag_pending=True  -> the in-app request is still waiting for the host
                          watcher to pick it up (update.sh --watch).
    flag_pending=False -> the watcher has consumed the flag (pull/rebuild
                          in progress or done). The frontend then watches
                          /api/health for the version to change.
    """
    return {
        "flag_pending": os.path.exists(UPDATE_FLAG),
        "version": get_local_version(),
    }


def request_update():
    """Drop the flag the host watcher looks for. Returns the manual fallback cmd."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(UPDATE_FLAG, "w") as f:
        json.dump({"requested": True}, f)
    return {
        "queued": True,
        "message": "Update queued. The host watcher will pull the new version "
                   "and rebuild the container within ~1 minute.",
        "manual_command": "cd $(dirname $(readlink -f $0)) && git pull && "
                          "docker compose up -d --build",
    }
