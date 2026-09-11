"""Offline signed-license activation.

Same mechanism as WorkshopIQ's app/services/licensing.py — this install only
runs once a valid license key has been entered. A license key is a small
Ed25519-signed token generated *outside* this codebase (the license-server
toolkit, kept private) — nothing here can produce a valid one, only verify
it. Verification is fully offline: no call home, no dependency on this
server having internet access.

Deliberately kept in sync with every other app on the same license-server:
they all verify against the SAME Ed25519 public key (one signing keypair,
one issuing tool, many products), distinguished only by PRODUCT below
matching whatever was typed into the "Product" field at issue time.

Format of a license key string::

    WIQL1.<base64url(payload_json)>.<base64url(signature)>

``payload_json`` (UTF-8, no whitespace requirements) looks like::

    {
      "license_id": "...",       # opaque id, for the issuer's own records
      "product": "guestiq",      # must match PRODUCT below
      "client": "Some Lodge",    # display name, shown once activated
      "server_id": "<hex>",      # must match this install's own server_id
      "issued_at": "2026-09-11T00:00:00Z",
      "expires_at": null         # ISO 8601 UTC, or null for a perpetual license
    }

The signature covers the exact ``payload_json`` bytes embedded in the token
(after base64url-decoding the middle segment) — the generator and this
verifier must agree byte-for-byte, which is why both sides use
``json.dumps(..., separators=(",", ":"), sort_keys=True)``.

Verification result is cached briefly so the per-request gate in ``main.py``
doesn't do a DB round-trip — and a fresh Ed25519 verify, which is cheap but
not free — on every single request.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import database as db

PRODUCT = "guestiq"

# Public half of the offline signing key. Safe to ship — it can only verify
# signatures, never create them. Same keypair baked into every product on
# this license-server (see WorkshopIQ's app/services/licensing.py).
_PUBLIC_KEY_HEX = "ecb4802e522dc2cc0a820824406ba004d4f70b9afea7e1325095d77309842f25"
_PUBLIC_KEY = Ed25519PublicKey.from_public_bytes(bytes.fromhex(_PUBLIC_KEY_HEX))

_TOKEN_PREFIX = "WIQL1."

CACHE_TTL = 3.0
_cache: dict = {"status": None, "at": 0.0}


def bust_cache() -> None:
    """Force the next status check to re-verify instead of using the cached
    result — called right after a successful activation."""
    _cache["at"] = 0.0


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64u_decode_strict(s: str) -> bytes:
    """Like :func:`_b64u_decode`, but rejects any string that isn't the
    canonical encoding of its own decoded bytes (see WorkshopIQ's licensing.py
    for the full rationale — avoids a mis-typed final base64 character
    silently "still working")."""
    raw = _b64u_decode(s)
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != s:
        raise ValueError("non-canonical base64")
    return raw


def parse_and_verify(license_key: str) -> dict | None:
    """Verify a license key's signature and return its payload dict, or
    ``None`` if the key is malformed, unsigned by us, or not otherwise
    parseable. Does NOT check server_id/product/expiry — see
    :func:`evaluate`."""
    key = (license_key or "").strip()
    if not key.startswith(_TOKEN_PREFIX):
        return None
    body = key[len(_TOKEN_PREFIX):]
    try:
        payload_b64, sig_b64 = body.split(".")
        payload_bytes = _b64u_decode_strict(payload_b64)
        signature = _b64u_decode_strict(sig_b64)
    except Exception:  # noqa: BLE001 — any malformed token
        return None
    try:
        _PUBLIC_KEY.verify(signature, payload_bytes)
    except InvalidSignature:
        return None
    try:
        payload = json.loads(payload_bytes)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_expired(payload: dict) -> bool:
    expires_at = payload.get("expires_at")
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        # An unparseable expiry is treated as expired rather than silently
        # granting a perpetual license on malformed data.
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= exp


def evaluate(license_key: str, server_id: str) -> dict:
    """Full check: signature, product match, server binding, expiry.

    Returns ``{"activated": bool, "reason": str | None, ...payload fields}``.
    """
    payload = parse_and_verify(license_key)
    if payload is None:
        return {"activated": False, "reason": "invalid_or_unsigned"}
    if payload.get("product") != PRODUCT:
        return {"activated": False, "reason": "wrong_product"}
    if server_id and payload.get("server_id") != server_id:
        return {"activated": False, "reason": "server_mismatch"}
    if _is_expired(payload):
        return {"activated": False, "reason": "expired", **payload}
    return {"activated": True, "reason": None, **payload}


def get_or_create_server_id() -> str:
    """This install's own identity for license binding: a random id generated
    once on first boot and persisted in the settings row (not tied to
    hardware, which is fragile under Docker/virtualization — a persisted
    random id is the standard approach for self-hosted containerised apps)."""
    with db.get_db() as conn:
        row = conn.execute("SELECT server_id FROM settings WHERE id = 1").fetchone()
        server_id = (row["server_id"] if row else "") or ""
        if server_id:
            return server_id
        server_id = secrets.token_hex(16)
        conn.execute("UPDATE settings SET server_id = ? WHERE id = 1", (server_id,))
    return server_id


def get_license_key() -> str:
    with db.get_db() as conn:
        row = conn.execute("SELECT license_key FROM settings WHERE id = 1").fetchone()
    return (row["license_key"] if row else "") or ""


def get_status(*, use_cache: bool = True) -> dict:
    """The gate's source of truth. Cached briefly (see module docstring)."""
    now = time.monotonic()
    if use_cache and _cache["status"] is not None and now - _cache["at"] < CACHE_TTL:
        return _cache["status"]
    try:
        server_id = get_or_create_server_id()
        license_key = get_license_key()
    except Exception:  # noqa: BLE001 — never let the gate take the app down
        cached = _cache["status"]
        if cached is not None:
            return cached
        return {"activated": False, "reason": "db_unavailable", "server_id": ""}

    if not license_key:
        status = {"activated": False, "reason": "not_activated", "server_id": server_id}
    else:
        result = evaluate(license_key, server_id)
        status = {**result, "server_id": server_id}

    _cache["status"] = status
    _cache["at"] = now
    return status


def activate(license_key: str) -> dict:
    """Verify and, if valid, persist a submitted license key."""
    license_key = (license_key or "").strip()
    server_id = get_or_create_server_id()
    if not license_key:
        return {"activated": False, "reason": "empty", "server_id": server_id}

    result = evaluate(license_key, server_id)
    if result["activated"]:
        with db.get_db() as conn:
            conn.execute("UPDATE settings SET license_key = ? WHERE id = 1", (license_key,))
        bust_cache()
    return {**result, "server_id": server_id}
