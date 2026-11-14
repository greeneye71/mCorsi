"""Ritardo progressivo sui codici corso errati, per utente e per IP."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import CourseCodeFailure, User, utc_now
from .audit import record_event
from .otp import _aware

FAILURE_WINDOW = timedelta(hours=1)
MAX_DELAY_SECONDS = 300


class CourseCodeThrottled(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Troppi tentativi: riprova tra {retry_after} secondi.")


def delay_for_failures(failures: int) -> int:
    if failures <= 1:
        return 0
    return min(MAX_DELAY_SECONDS, 2 ** (failures - 1))


def _subjects(user_id: str, ip: str) -> list[tuple[str, str]]:
    return [("user", user_id), ("ip", ip)]


def _live_row(scope: str, subject: str, now: datetime) -> CourseCodeFailure | None:
    row = CourseCodeFailure.query.filter_by(scope=scope, subject=subject).first()
    if row is not None and now - _aware(row.last_failure_at) > FAILURE_WINDOW:
        db.session.delete(row)
        db.session.flush()
        return None
    return row


def check_course_code_allowed(user_id: str, ip: str, *, now: datetime | None = None) -> None:
    now = now or utc_now()
    remaining = timedelta(0)
    for scope, subject in _subjects(user_id, ip):
        row = _live_row(scope, subject, now)
        if row is not None and row.blocked_until is not None:
            remaining = max(remaining, _aware(row.blocked_until) - now)
    if remaining > timedelta(0):
        raise CourseCodeThrottled(max(1, math.ceil(remaining.total_seconds())))


def _increment(scope: str, subject: str, now: datetime) -> int:
    """Incrementa in modo atomico, creando la riga se manca (anche in concorrenza)."""
    if _live_row(scope, subject, now) is None:
        try:
            with db.session.begin_nested():
                db.session.add(
                    CourseCodeFailure(scope=scope, subject=subject, failures=0, last_failure_at=now)
                )
        except IntegrityError:
            pass  # un'altra richiesta l'ha appena creata: si incrementa quella
    query = CourseCodeFailure.query.filter_by(scope=scope, subject=subject)
    query.update(
        {
            CourseCodeFailure.failures: CourseCodeFailure.failures + 1,
            CourseCodeFailure.last_failure_at: now,
        },
        synchronize_session=False,
    )
    row = query.populate_existing().one()
    delay = delay_for_failures(row.failures)
    row.blocked_until = now + timedelta(seconds=delay) if delay else None
    return row.failures


def record_course_code_failure(user: User, ip: str, *, now: datetime | None = None) -> int:
    now = now or utc_now()
    counts = [_increment(scope, subject, now) for scope, subject in _subjects(user.id, ip)]
    failures = max(counts)
    record_event(
        "course_code.failed",
        actor=user,
        target_type="user",
        target_id=user.id,
        detail={"ip": ip, "failures": failures},
    )
    return failures


def reset_course_code_failures(user_id: str, ip: str) -> None:
    for scope, subject in _subjects(user_id, ip):
        CourseCodeFailure.query.filter_by(scope=scope, subject=subject).delete()
