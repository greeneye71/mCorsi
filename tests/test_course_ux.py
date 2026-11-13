from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from mcorsi.extensions import db
from mcorsi.models import (
    AdmissionRequest,
    AuditLog,
    Certificate,
    Course,
    Enrollment,
    StoredFile,
    User,
)
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


def test_add_unknown_email_with_names_creates_and_enrolls(app, client):
    course_id, _participant_id = _open_course_with_participant(app, client)
    response = client.post(
        f"/courses/{course_id}/admissions",
        data={"email": "Nuovo@Example.it", "first_name": "Mario", "last_name": "Rossi"},
        follow_redirects=True,
    )
    page = response.get_data(as_text=True)
    assert "creato e iscritto" in page
    assert "Completa" in page
    with app.app_context():
        user = User.query.filter_by(email="nuovo@example.it").one()
        assert user.has_role("participant") and not user.profile_completed
        assert user.participant_profile is not None
        assert Enrollment.query.filter_by(participant_user_id=user.id).count() == 1


def test_add_unknown_email_without_names_asks_for_them(app, client):
    course_id, _participant_id = _open_course_with_participant(app, client)
    response = client.post(
        f"/courses/{course_id}/admissions",
        data={"email": "nuovo@example.it", "first_name": "Mario"},
        follow_redirects=True,
    )
    assert "indica nome e cognome" in response.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(email="nuovo@example.it").first() is None
        assert Enrollment.query.count() == 0


def test_add_staff_email_is_refused(app, client):
    course_id, _participant_id = _open_course_with_participant(app, client)
    operator_id = _make_user(app, "operatore@example.it", "operator")
    response = client.post(
        f"/courses/{course_id}/admissions",
        data={"email": "operatore@example.it", "first_name": "Op", "last_name": "Era"},
        follow_redirects=True,
    )
    assert "appartiene a un utente dello staff" in response.get_data(as_text=True)
    with app.app_context():
        operator = db.session.get(User, operator_id)
        assert [role.name for role in operator.roles] == ["operator"]
        assert Enrollment.query.count() == 0
        assert AdmissionRequest.query.count() == 0


def _course_of_operator_a(app):
    referent_id = _make_user(app, "referente@example.it", "operator")
    _make_user(app, "altro@example.it", "operator")
    _make_user(app, "persona@example.it", "participant")
    second_id = _make_user(app, "seconda@example.it", "participant")
    with app.app_context():
        from datetime import date, time

        from mcorsi.services.courses import create_course

        referent = db.session.get(User, referent_id)
        course = create_course(
            actor=referent,
            data={
                "title": "Sicurezza",
                "status": "open",
                "referent_user_id": referent_id,
                "session_date": date(2026, 10, 1),
                "start_time": time(9, 0),
                "end_time": time(12, 0),
                "delivery_mode": "online",
                "certificate_validity_months": 60,
            },
        )
        second = db.session.get(User, second_id)
        db.session.flush()
        pending = request_admission(course, second, actor=second)
        db.session.commit()
        return course.id, pending.id


def test_any_operator_can_enroll_and_decide(app, client):
    course_id, pending_id = _course_of_operator_a(app)
    _login(client, "altro@example.it")

    response = client.post(f"/courses/{course_id}/admissions", data={"email": "persona@example.it"})
    assert response.status_code == 302
    with app.app_context():
        assert Enrollment.query.count() == 1

    response = client.post(f"/courses/{course_id}/admissions/{pending_id}/approve", data={})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(AdmissionRequest, pending_id).status == "approved"


def test_participant_cannot_enroll_or_decide(app, client):
    course_id, pending_id = _course_of_operator_a(app)
    with app.app_context():
        auth_id = User.query.filter_by(email="persona@example.it").one().get_id()
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = auth_id
        browser_session["_fresh"] = True

    response = client.post(f"/courses/{course_id}/admissions", data={"email": "persona@example.it"})
    assert response.status_code == 403
    response = client.post(f"/courses/{course_id}/admissions/{pending_id}/approve", data={})
    assert response.status_code == 403
    with app.app_context():
        assert Enrollment.query.count() == 0
        assert db.session.get(AdmissionRequest, pending_id).status == "pending"


def _seed_listing(app, admin_id):
    from datetime import date, time

    from mcorsi.services.courses import create_course

    with app.app_context():
        admin = db.session.get(User, admin_id)
        ids = {}
        for title, day, status in [
            ("Antincendio", date(2026, 3, 1), "open"),
            ("Primo soccorso", date(2026, 6, 1), "draft"),
            ("Antincendio avanzato", date(2026, 9, 1), "completed"),
        ]:
            course = create_course(
                actor=admin,
                data={
                    "title": title,
                    "referent_user_id": admin_id,
                    "session_date": day,
                    "start_time": time(9, 0),
                    "end_time": time(13, 0),
                    "delivery_mode": "online",
                    "status": status,
                },
            )
            ids[title] = course.id
        db.session.commit()
        return ids


def test_course_list_search_filter_and_order(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    _seed_listing(app, admin_id)

    page = client.get("/courses").get_data(as_text=True)
    assert page.index(">Antincendio avanzato<") < page.index(">Primo soccorso<") < page.index(">Antincendio<")
    assert "/duplicate" in page

    page = client.get("/courses?q=antinc").get_data(as_text=True)
    assert ">Primo soccorso<" not in page
    assert ">Antincendio<" in page and ">Antincendio avanzato<" in page

    page = client.get("/courses?status=draft").get_data(as_text=True)
    assert ">Primo soccorso<" in page and ">Antincendio<" not in page

    assert client.get("/courses?status=xyz").status_code == 200


def test_pending_filter_and_dashboard_link(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _make_user(app, "persona@example.it", "participant", first_name="Pia", last_name="Neri")
    _login(client, "admin@example.it")
    ids = _seed_listing(app, admin_id)
    with app.app_context():
        participant = User.query.filter_by(email="persona@example.it").one()
        request_admission(db.session.get(Course, ids["Antincendio"]), participant, actor=participant)
        db.session.commit()

    page = client.get("/courses?pending=1").get_data(as_text=True)
    assert ">Antincendio<" in page
    assert ">Primo soccorso<" not in page and ">Antincendio avanzato<" not in page

    dashboard = client.get("/").get_data(as_text=True)
    assert "/courses?pending=1" in dashboard


def test_duplicate_defaults_to_today(app, client):
    from datetime import date

    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    ids = _seed_listing(app, admin_id)
    page = client.get(f"/courses/{ids['Antincendio']}/duplicate").get_data(as_text=True)
    assert date.today().isoformat() in page


def _course_with_enrollments(app, client, count):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    course_id = _new_course(app, client, admin_id)
    client.post(f"/courses/{course_id}/status", data={"status": "open"})
    ids = []
    for index in range(count):
        _make_user(app, f"p{index}@example.it", "participant")
        client.post(f"/courses/{course_id}/admissions", data={"email": f"p{index}@example.it"})
        with app.app_context():
            participant = User.query.filter_by(email=f"p{index}@example.it").one()
            ids.append(Enrollment.query.filter_by(participant_user_id=participant.id).one().id)
    return admin_id, course_id, ids


def test_mark_all_attended_keeps_absent(app, client):
    _, course_id, ids = _course_with_enrollments(app, client, 3)
    with app.app_context():
        db.session.get(Enrollment, ids[2]).attendance_status = "absent"
        db.session.commit()
    response = client.post(f"/documents/courses/{course_id}/attendance/all", follow_redirects=True)
    assert "2 presenze confermate." in response.get_data(as_text=True)
    with app.app_context():
        statuses = [db.session.get(Enrollment, item).attendance_status for item in ids]
        assert statuses == ["attended", "attended", "absent"]
        assert AuditLog.query.filter_by(event_type="enrollment.attendance_updated").count() == 2


def test_generate_all_only_ready_and_not_already_issued(app, client, monkeypatch):
    admin_id, course_id, ids = _course_with_enrollments(app, client, 3)
    ready_id, issued_id, not_ready_id = ids
    with app.app_context():
        enrollment = db.session.get(Enrollment, issued_id)
        stored = StoredFile(
            storage_key="test/issued.pdf",
            original_name="issued.pdf",
            mime_type="application/pdf",
            size_bytes=1,
            sha256="0" * 64,
            uploaded_by_user_id=admin_id,
        )
        db.session.add(
            Certificate(
                participant_user_id=enrollment.participant_user_id,
                course_id=course_id,
                enrollment=enrollment,
                pdf_file=stored,
                certificate_number="GIA-1",
                title_snapshot="Corso",
                course_date=date.today(),
            )
        )
        db.session.commit()

    calls = []

    def fake_generate(enrollment, *, actor):
        calls.append(enrollment.id)
        return SimpleNamespace(id="fake", certificate_number="N-1")

    monkeypatch.setattr("mcorsi.documents.routes.generate_certificate", fake_generate)
    monkeypatch.setattr(
        "mcorsi.documents.routes.readiness", lambda e: (e.id in {ready_id, issued_id}, [])
    )
    response = client.post(f"/documents/courses/{course_id}/certificates/all", follow_redirects=True)
    assert calls == [ready_id]
    assert "1 attestati generati, 1 non pronti." in response.get_data(as_text=True)
