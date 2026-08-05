from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from flask import current_app

from ..extensions import db
from ..models import McpAccessToken, User
from .audit import record_event


MCP_SCOPES = (
    "courses:read",
    "admissions:read",
    "participants:read",
    "certificates:read",
    "notifications:read",
    "automation:write",
)


def _digest(raw_token: str) -> str:
    pepper = current_app.config["MCP_TOKEN_PEPPER"].encode("utf-8")
    return hmac.new(pepper, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def create_access_token(
    *, name: str, scopes: list[str], creator: User, expires_at: datetime | None
) -> tuple[str, McpAccessToken]:
    clean_name = name.strip()
    clean_scopes = sorted(set(scopes))
    if not clean_name:
        raise ValueError("Il nome del token è obbligatorio.")
    invalid = set(clean_scopes) - set(MCP_SCOPES)
    if invalid:
        raise ValueError("Permessi MCP non validi: " + ", ".join(sorted(invalid)))
    if not clean_scopes:
        raise ValueError("Seleziona almeno un permesso MCP.")
    prefix = secrets.token_urlsafe(9).replace("-", "A").replace("_", "B")[:12]
    raw_token = f"mcorsi_{prefix}_{secrets.token_urlsafe(32)}"
    access = McpAccessToken(
        name=clean_name,
        token_prefix=prefix,
        token_hash=_digest(raw_token),
        scopes=clean_scopes,
        expires_at=expires_at,
        created_by_user_id=creator.id,
    )
    db.session.add(access)
    db.session.flush()
    record_event(
        "mcp.token_created",
        actor=creator,
        target_type="mcp_access_token",
        target_id=access.id,
        detail={"name": clean_name, "prefix": prefix, "scopes": clean_scopes},
    )
    return raw_token, access


def verify_access_token(raw_token: str, *, update_last_used: bool = True) -> McpAccessToken | None:
    parts = raw_token.split("_", 2)
    if len(parts) != 3 or parts[0] != "mcorsi":
        return None
    access = McpAccessToken.query.filter_by(token_prefix=parts[1], is_active=True).first()
    if access is None or not hmac.compare_digest(access.token_hash, _digest(raw_token)):
        return None
    now = datetime.now(timezone.utc)
    expiry = access.expires_at
    if expiry is not None:
        expiry = expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            return None
    if update_last_used:
        access.last_used_at = now
        db.session.commit()
    return access
