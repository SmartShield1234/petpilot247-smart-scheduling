"""PetPilot247 HighLevel OAuth routes. No booking writes.

Install with app.include_router(router). Run initialize_oauth_tables at startup
with a separately provisioned PostgreSQL schema. Requires an authorized
HighLevel install URL that propagates the OAuth state parameter.
"""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import psycopg
from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter(tags=["PetPilot247 OAuth"])
CALLBACK = "https://petpilot247-sync-dev.onrender.com/oauth/petpilot247/callback"
TOKEN_URL = "https://services.leadconnectorhq.com/oauth/token"


def _settings():
    required = (
        "PETPILOT_POSTGRES_URL", "PETPILOT_GHL_OAUTH_CLIENT_ID",
        "PETPILOT_GHL_OAUTH_CLIENT_SECRET", "PETPILOT_GHL_OAUTH_FERNET_KEY",
        "GHL_LOCATION_ID", "PETPILOT_GHL_INSTALL_URL",
    )
    values = {key: os.environ.get(key, "").strip() for key in required}
    if any(not value for value in values.values()):
        raise HTTPException(503, "OAuth not configured")
    try:
        Fernet(values["PETPILOT_GHL_OAUTH_FERNET_KEY"].encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "OAuth encryption key invalid") from exc
    return values


def initialize_oauth_tables(connection_url: str):
    """Run once from a controlled migration/startup before using OAuth."""
    with psycopg.connect(connection_url, sslmode="require") as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS petpilot_oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS petpilot_oauth_installations (
                    location_id TEXT PRIMARY KEY,
                    access_encrypted BYTEA NOT NULL,
                    refresh_encrypted BYTEA NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    scopes TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)


def _state_digest(state: str) -> str:
    import hashlib
    return hashlib.sha256(state.encode("ascii")).hexdigest()


@router.get("/oauth/petpilot247/start")
def start():
    """Start only through this server route; users cannot supply OAuth state."""
    settings = _settings()
    state = secrets.token_urlsafe(32)
    with psycopg.connect(settings["PETPILOT_POSTGRES_URL"], sslmode="require") as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("DELETE FROM petpilot_oauth_states WHERE expires_at < NOW()")
            cur.execute("INSERT INTO petpilot_oauth_states (state_hash, expires_at) "
                        "VALUES (%s, NOW() + INTERVAL '10 minutes')", (_state_digest(state),))
    install_url = settings["PETPILOT_GHL_INSTALL_URL"]
    parts = urlsplit(install_url)
    if parts.scheme != "https" or not parts.netloc:
        raise HTTPException(503, "Invalid install URL")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["state"] = state
    return RedirectResponse(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                        urlencode(query), parts.fragment)), status_code=302)


@router.get("/oauth/petpilot247/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        raise HTTPException(400, "HighLevel authorization denied")
    if not code or not state or len(code) > 4096 or len(state) > 256:
        raise HTTPException(400, "Missing or invalid authorization response")
    settings = _settings()
    # Atomic, single-use consume prevents replay. A failed exchange requires restart.
    with psycopg.connect(settings["PETPILOT_POSTGRES_URL"], sslmode="require") as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("DELETE FROM petpilot_oauth_states "
                        "WHERE state_hash = %s AND expires_at > NOW() RETURNING state_hash",
                        (_state_digest(state),))
            if cur.fetchone() is None:
                raise HTTPException(400, "Expired or invalid OAuth state")

    form = {
        "client_id": settings["PETPILOT_GHL_OAUTH_CLIENT_ID"],
        "client_secret": settings["PETPILOT_GHL_OAUTH_CLIENT_SECRET"],
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": CALLBACK,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TOKEN_URL, data=form,
                                         headers={"Accept": "application/json"})
            response.raise_for_status()
            token = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "HighLevel OAuth token exchange failed") from exc

    location = token.get("locationId") or token.get("location_id")
    # Never accept company-wide tokens or another location in this pilot.
    if token.get("userType") not in ("Location", "location") or location != settings["GHL_LOCATION_ID"]:
        raise HTTPException(403, "OAuth installation does not match PetPilot247 location")
    access, refresh = token.get("access_token"), token.get("refresh_token")
    expires = token.get("expires_in")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise HTTPException(502, "Incomplete token response")
    if not isinstance(expires, (int, float)) or not (0 < expires <= 1000000):
        raise HTTPException(502, "Invalid token expiry")
    encrypt = Fernet(settings["PETPILOT_GHL_OAUTH_FERNET_KEY"].encode())
    with psycopg.connect(settings["PETPILOT_POSTGRES_URL"], sslmode="require") as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("""
                INSERT INTO petpilot_oauth_installations
                (location_id, access_encrypted, refresh_encrypted, expires_at, scopes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (location_id) DO UPDATE SET
                    access_encrypted=EXCLUDED.access_encrypted,
                    refresh_encrypted=EXCLUDED.refresh_encrypted,
                    expires_at=EXCLUDED.expires_at,
                    scopes=EXCLUDED.scopes,
                    updated_at=NOW()
            """, (location, encrypt.encrypt(access.encode()), encrypt.encrypt(refresh.encode()),
                  datetime.now(timezone.utc) + timedelta(seconds=expires),
                  str(token.get("scope", ""))))
    return HTMLResponse("<h2>PetPilot247 authorization recorded</h2>"
                        "<p>You may close this window.</p>",
                        headers={"Cache-Control": "no-store"})
