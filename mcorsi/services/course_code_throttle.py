"""Ritardo progressivo sui codici corso errati, per utente e per IP."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

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


def record_course_code_failure(user: User, ip: str, *, now: datetime | None = None) -> int:
    now = now or utc_now()
    counts = []
    for scope, subject in _subjects(user.id, ip):
        row = _live_row(scope, subject, now)
        if row is None:
            row = CourseCodeFailure(scope=scope, subject=subject, failures=0)
            db.session.add(row)
        row.failures += 1
        row.last_failure_at = now
        delay = delay_for_failures(row.failures)
        row.blocked_until = now + timedelta(seconds=delay) if delay else None
        counts.append(row.failures)
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
