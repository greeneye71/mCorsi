from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mcorsi.extensions import db
from mcorsi.models import AuditLog, CourseCodeFailure, Role, User
from mcorsi.services.course_code_throttle import (
    CourseCodeThrottled,
    check_course_code_allowed,
    delay_for_failures,
    record_course_code_failure,
    reset_course_code_failures,
)

T0 = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def _participant(email="persona@example.it") -> User:
    user = User(email=email, first_name="Ada", profile_completed=True)
    user.roles.append(Role.query.filter_by(name="participant").one())
    db.session.add(user)
    db.session.commit()
    return user


def _fail(user, ip="10.0.0.1", *, now=T0, times=1) -> int:
    result = 0
    for _ in range(times):
        result = record_course_code_failure(user, ip, now=now)
        db.session.commit()
    return result


def test_delay_sequence():
    assert [delay_for_failures(n) for n in (1, 2, 3, 4, 9, 10, 20)] == [0, 2, 4, 8, 256, 300, 300]


def test_first_failure_does_not_block(app):
    with app.app_context():
        user = _participant()
        _fail(user)
        check_course_code_allowed(user.id, "10.0.0.1", now=T0)


def test_second_and_third_failure_block_2_and_4_seconds(app):
    with app.app_context():
        user = _participant()
        _fail(user, times=2)
        with pytest.raises(CourseCodeThrottled) as exc:
            check_course_code_allowed(user.id, "10.0.0.1", now=T0 + timedelta(seconds=1))
        assert exc.value.retry_after == 1
        assert str(exc.value) == "Troppi tentativi: riprova tra 1 secondi."
        check_course_code_allowed(user.id, "10.0.0.1", now=T0 + timedelta(seconds=2))

        _fail(user, now=T0 + timedelta(seconds=2))
        with pytest.raises(CourseCodeThrottled) as exc:
            check_course_code_allowed(user.id, "10.0.0.1", now=T0 + timedelta(seconds=3))
        assert exc.value.retry_after == 3


def test_delay_capped_at_300_seconds(app):
    with app.app_context():
        user = _participant()
        _fail(user, times=12)
        row = CourseCodeFailure.query.filter_by(scope="user", subject=user.id).one()
        assert row.blocked_until - row.last_failure_at == timedelta(seconds=300)


def test_ip_block_applies_to_other_users(app):
    with app.app_context():
        user_a = _participant("a@example.it")
        user_b = _participant("b@example.it")
        _fail(user_a, times=3)
        with pytest.raises(CourseCodeThrottled):
            check_course_code_allowed(user_b.id, "10.0.0.1", now=T0)
        check_course_code_allowed(user_b.id, "10.0.0.2", now=T0)


def test_reset_clears_user_and_ip(app):
    with app.app_context():
        user = _participant()
        _fail(user, times=3)
        reset_course_code_failures(user.id, "10.0.0.1")
        db.session.commit()
        check_course_code_allowed(user.id, "10.0.0.1", now=T0)
        assert CourseCodeFailure.query.count() == 0


def test_failures_expire_after_one_hour(app):
    with app.app_context():
        user = _participant()
        _fail(user, times=5)
        assert _fail(user, now=T0 + timedelta(minutes=61)) == 1


def test_failure_audit_never_contains_code(app):
    with app.app_context():
        user = _participant()
        _fail(user)
        entry = AuditLog.query.filter_by(event_type="course_code.failed").one()
        assert entry.actor_user_id == user.id
        assert entry.detail == {"ip": "10.0.0.1", "failures": 1}


def test_concurrent_first_failure_does_not_crash(app, monkeypatch):
    """Un'altra richiesta inserisce la riga tra la lettura e l'insert."""
    from mcorsi.services import course_code_throttle as throttle

    with app.app_context():
        user = _participant()
        _fail(user)  # righe user/ip già presenti (failures=1)
        monkeypatch.setattr(throttle, "_live_row", lambda scope, subject, now: None)

        failures = _fail(user)

        assert failures == 2
        rows = CourseCodeFailure.query.all()
        assert len(rows) == 2
        assert all(row.failures == 2 for row in rows)
        assert all(row.blocked_until is not None for row in rows)


def test_empty_ip_does_not_share_bucket(app):
    with app.app_context():
        first = _participant()
        second = _participant("altra@example.it")
        _fail(first, ip="", times=3)
        check_course_code_allowed(second.id, "", now=T0)
        assert CourseCodeFailure.query.filter_by(scope="ip").count() == 0


def test_failure_purges_expired_rows(app):
    with app.app_context():
        stale = _participant()
        fresh = _participant("altra@example.it")
        _fail(stale, ip="10.0.0.1")
        _fail(fresh, ip="10.0.0.2", now=T0 + timedelta(hours=2))
        subjects = {row.subject for row in CourseCodeFailure.query.all()}
        assert subjects == {fresh.id, "10.0.0.2"}
