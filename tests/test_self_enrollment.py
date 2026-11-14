from __future__ import annotations

from datetime import date, time

import pytest

from mcorsi.extensions import db
from mcorsi.models import AdmissionRequest, AuditLog, Enrollment, Role, User
from mcorsi.services.courses import (
    CourseOperationError,
    create_course,
    decide_admission,
    request_admission,
    self_enroll,
)

GENERIC = "Codice non valido o corso non aperto alle richieste."


def _user(email: str, role: str) -> User:
    user = User(email=email, first_name="Ada", profile_completed=True)
    user.roles.append(Role.query.filter_by(name=role).one())
    db.session.add(user)
    db.session.flush()
    return user


def _course(*, status="open", enabled=True):
    referent = _user("referente@example.it", "operator")
    course = create_course(
        actor=referent,
        data={
            "title": "Radioprotezione",
            "referent_user_id": referent.id,
            "delivery_mode": "online",
            "session_date": date(2026, 12, 1),
            "start_time": time(9, 0),
            "end_time": time(13, 0),
            "self_enrollment_enabled": enabled,
        },
    )
    course.status = status
    db.session.commit()
    return course, referent


@pytest.mark.parametrize("status", ["open", "in_progress"])
def test_self_enroll_creates_enrollment(app, status):
    with app.app_context():
        course, _ = _course(status=status)
        participant = _user("persona@example.it", "participant")
        enrollment = self_enroll(course, participant)
        db.session.commit()
        assert Enrollment.query.filter_by(course_id=course.id, participant_user_id=participant.id).one() is enrollment
        admission = AdmissionRequest.query.filter_by(course_id=course.id).one()
        assert admission.status == "approved"
        assert admission.decision_message == "Iscrizione diretta con codice"
        event = AuditLog.query.filter_by(event_type="enrollment.self_enrolled").one()
        assert event.target_id == course.id
        assert event.detail == {"participant": participant.id}


@pytest.mark.parametrize(
    "status,enabled",
    [("draft", True), ("completed", True), ("canceled", True), ("archived", True), ("open", False)],
)
def test_self_enroll_rejects_closed_states(app, status, enabled):
    with app.app_context():
        course, _ = _course(status=status, enabled=enabled)
        participant = _user("persona@example.it", "participant")
        with pytest.raises(CourseOperationError) as exc:
            self_enroll(course, participant)
        assert str(exc.value) == GENERIC
        assert Enrollment.query.count() == 0


def test_self_enroll_approves_pending_request(app):
    with app.app_context():
        course, _ = _course()
        participant = _user("persona@example.it", "participant")
        pending = request_admission(course, participant)
        db.session.commit()
        self_enroll(course, participant)
        db.session.commit()
        assert AdmissionRequest.query.count() == 1
        assert db.session.get(AdmissionRequest, pending.id).status == "approved"
        assert Enrollment.query.count() == 1


def test_self_enroll_already_enrolled_no_duplicate(app):
    with app.app_context():
        course, _ = _course()
        participant = _user("persona@example.it", "participant")
        self_enroll(course, participant)
        db.session.commit()
        with pytest.raises(CourseOperationError) as exc:
            self_enroll(course, participant)
        assert str(exc.value) == "Sei già iscritto a questo corso."
        assert Enrollment.query.count() == 1


def test_self_enroll_rejected_request_blocks(app):
    with app.app_context():
        course, referent = _course()
        participant = _user("persona@example.it", "participant")
        admission = request_admission(course, participant)
        db.session.flush()
        decide_admission(admission, actor=referent, approve=False)
        db.session.commit()
        with pytest.raises(CourseOperationError) as exc:
            self_enroll(course, participant)
        assert str(exc.value) == "La tua richiesta per questo corso è stata respinta: contatta il referente."
        assert Enrollment.query.count() == 0
