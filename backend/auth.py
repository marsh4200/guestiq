"""
GuestIQ - accounts, roles and permissions.

Two roles:
  admin  - everything, including managing staff accounts and passwords.
  staff  - reception work only by default: check guests in, check them out,
           extend a stay and add / edit guest records. Everything else
           (rooms, QR codes, settings, automation, updates, deleting anything,
           and any password change) is off until an admin grants it.
"""
import json
from typing import Optional

from fastapi import Depends, Header, HTTPException

from . import database as db

# ---------------------------------------------------------------------------
# What staff can be granted. Anything not listed here is admin-only.
# ---------------------------------------------------------------------------
PERMISSIONS = [
    {"key": "rooms",         "group": "Rooms",    "label": "Add & edit rooms"},
    {"key": "rooms_delete",  "group": "Rooms",    "label": "Delete rooms"},
    {"key": "guests_delete", "group": "Guests",   "label": "Delete guest records"},
    {"key": "qr",            "group": "QR codes", "label": "View & print QR codes"},
    {"key": "settings",      "group": "System",   "label": "Change hotel settings"},
    {"key": "automation",    "group": "System",   "label": "Automation & smart control"},
    {"key": "updates",       "group": "System",   "label": "Check & apply updates"},
]
PERMISSION_KEYS = [p["key"] for p in PERMISSIONS]

# Always available to every signed-in user, admin or staff.
BASE_CAPABILITIES = [
    "View the check-ins dashboard and alerts",
    "Check guests in (pending arrivals and manual)",
    "Check guests out and extend a stay",
    "Add and edit guest records",
]


def perms_of(user: dict) -> set:
    if not user:
        return set()
    if user.get("role") == "admin":
        return set(PERMISSION_KEYS)
    try:
        raw = json.loads(user.get("permissions") or "[]")
    except (ValueError, TypeError):
        raw = []
    return {p for p in raw if p in PERMISSION_KEYS}


def clean_perms(values) -> str:
    """Normalise a submitted permission list into storable JSON."""
    if not values:
        return "[]"
    return json.dumps(sorted({v for v in values if v in PERMISSION_KEYS}))


def public_user(user: dict) -> dict:
    """User shape safe to hand to the browser — never the password hash."""
    if not user:
        return {}
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name") or user.get("username"),
        "role": user.get("role"),
        "active": bool(user.get("active", 1)),
        "permissions": sorted(perms_of(user)),
        "is_admin": user.get("role") == "admin",
        "last_login": user.get("last_login"),
        "created_at": user.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def _token_from_headers(authorization: Optional[str], x_auth_token: Optional[str]):
    token = x_auth_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    return token


def current_user(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
) -> dict:
    """Any signed-in user. This is the floor for every admin-console endpoint."""
    token = _token_from_headers(authorization, x_auth_token)
    user = db.session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user["_token"] = token
    return user


# Kept under the old name so existing endpoints read naturally.
require_user = current_user


def require_perm(perm: str):
    """Endpoint guard for one grantable permission."""
    def _dep(user: dict = Depends(current_user)) -> dict:
        if perm not in perms_of(user):
            raise HTTPException(
                status_code=403,
                detail="Your account doesn't have permission for that. "
                       "Ask an administrator to enable it.",
            )
        return user
    return _dep


def require_admin_role(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator access required.",
        )
    return user
