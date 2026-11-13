from __future__ import annotations

from mcorsi.extensions import db
from mcorsi.models import AdmissionRequest, Course, Enrollment, User
from mcorsi.services.courses import request_admission

from test_courses_and_participants import _course_payload, _login, _make_user


def _new_course(app, client, admin_id) -> str:
    response = client.post("/courses/new", data=_course_payload(admin_id))
    assert response.status_code == 302
    with app.app_context():
        return Course.query.order_by(Course.created_at.desc()).first().id


def test_new_course_is_always_draft_and_form_has_no_status(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    page = client.get("/courses/new").get_data(as_text=True)
    assert 'name="status"' not in page
    assert "La struttura dati supporta" not in page
    assert 'href="/courses"' in page
    assert "Titolo *" in page or "*</label>" in page
    client.post("/courses/new", data=_course_payload(admin_id) | {"status": "open"})
    with app.app_context():
        assert Course.query.one().status == "draft"


def test_status_buttons_follow_allowed_transitions(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    course_id = _new_course(app, client, admin_id)

    response = client.post(f"/courses/{course_id}/status", data={"status": "open"})
    assert response.status_code == 302
    with app.app_context():
        assert Course.query.get(course_id).status == "open"

    response = client.post(
        f"/courses/{course_id}/status", data={"status": "completed"}, follow_redirects=True
    )
    assert "Passaggio di stato non consentito." in response.get_data(as_text=True)
    with app.app_context():
        assert Course.query.get(course_id).status == "open"

    detail = client.get(f"/courses/{course_id}").get_data(as_text=True)
    assert "Avvia corso" in detail
    assert "Apri iscrizioni" not in detail
    assert "Annulla corso" in detail

    client.post(f"/courses/{course_id}/status", data={"status": "in_progress"})
    client.post(f"/courses/{course_id}/status", data={"status": "completed"})
    with app.app_context():
        assert Course.query.get(course_id).status == "completed"


def test_edit_does_not_change_status(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    course_id = _new_course(app, client, admin_id)
    client.post(f"/courses/{course_id}/status", data={"status": "open"})

    response = client.post(
        f"/courses/{course_id}/edit",
        data=_course_payload(admin_id, title="Nuovo titolo") | {"status": "draft"},
    )
    assert response.status_code == 302
    with app.app_context():
        course = Course.query.get(course_id)
        assert course.title == "Nuovo titolo"
        assert course.status == "open"


def _open_course_with_participant(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    participant_id = _make_user(app, "persona@example.it", "participant")
    _login(client, "admin@example.it")
    course_id = _new_course(app, client, admin_id)
    client.post(f"/courses/{course_id}/status", data={"status": "open"})
    return course_id, participant_id


def test_staff_add_enrolls_immediately(app, client):
    course_id, _ = _open_course_with_participant(app, client)
    response = client.post(
        f"/courses/{course_id}/admissions",
        data={"email": "persona@example.it"},
        follow_redirects=True,
    )
    assert "iscritto al corso." in response.get_data(as_text=True)
    with app.app_context():
        assert AdmissionRequest.query.one().status == "approved"
        assert Enrollment.query.count() == 1


def test_staff_add_approves_pending_portal_request(app, client):
    course_id, participant_id = _open_course_with_participant(app, client)
    with app.app_context():
        participant = db.session.get(User, participant_id)
        admission = request_admission(db.session.get(Course, course_id), participant, actor=participant)
        db.session.commit()
        admission_id = admission.id
    client.post(f"/courses/{course_id}/admissions", data={"email": "persona@example.it"})
    with app.app_context():
        admission = AdmissionRequest.query.one()
        assert admission.id == admission_id
        assert admission.status == "approved"
        assert Enrollment.query.count() == 1


def test_staff_add_twice_reports_already_enrolled(app, client):
    course_id, _ = _open_course_with_participant(app, client)
    client.post(f"/courses/{course_id}/admissions", data={"email": "persona@example.it"})
    response = client.post(
        f"/courses/{course_id}/admissions",
        data={"email": "persona@example.it"},
        follow_redirects=True,
    )
    assert "Il partecipante è già iscritto." in response.get_data(as_text=True)
    with app.app_context():
        assert Enrollment.query.count() == 1
