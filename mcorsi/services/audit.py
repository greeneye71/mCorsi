from __future__ import annotations

from flask import has_request_context, request

from ..extensions import db
from ..models import AuditLog, User


def record_event(
    event_type: str,
    *,
    actor: User | None = None,
    target_type: str = "",
    target_id: str = "",
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        event_type=event_type,
        target_type=target_type,
        target_id=str(target_id),
        detail=detail or {},
        ip_address=(request.remote_addr or "") if has_request_context() else "",
    )
    db.session.add(entry)
    return entry
