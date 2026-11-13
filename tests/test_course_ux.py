from __future__ import annotations

from mcorsi.models import Course

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
