from __future__ import annotations

from datetime import date, time

from mcorsi.extensions import db
from mcorsi.models import AdmissionRequest, AuditLog, Company, Course, Enrollment, User
from mcorsi.services.courses import create_course

from test_portal_otp import _admin, _profile_payload, _request_and_verify

GENERIC = "Codice non valido o corso non aperto alle richieste."
SESSION_KEY = "pending_self_enrollment"


def _course(app, *, status="open", enabled=True) -> tuple[str, str]:
    admin_id = _admin(app)
    with app.app_context():
        admin = db.session.get(User, admin_id)
        course = create_course(
            actor=admin,
            data={
                "title": "Radioprotezione",
                "description": "Corso online",
                "status": "open",
                "referent_user_id": admin_id,
                "session_date": date(2026, 11, 20),
                "start_time": time(9, 0),
                "end_time": time(13, 0),
                "delivery_mode": "online",
                "meeting_url": "",
                "certificate_validity_months": 60,
                "self_enrollment_enabled": enabled,
            },
        )
        course.status = status
        db.session.commit()
        return course.id, course.code


def _set_course(app, course_id, **fields):
    with app.app_context():
        course = db.session.get(Course, course_id)
        for name, value in fields.items():
            setattr(course, name, value)
        db.session.commit()


def _complete_profile(client):
    response = client.post("/participant/profile", data=_profile_payload())
    assert response.status_code == 302


def _flashes(client) -> list[str]:
    with client.session_transaction() as session:
        return [message for _, message in session.get("_flashes", [])]


def _pending_key(client):
    with client.session_transaction() as session:
        return session.get(SESSION_KEY)


def _enrollments(app) -> int:
    with app.app_context():
        return Enrollment.query.count()


def test_incomplete_profile_code_then_confirm_enrolls(app, client):
    course_id, code = _course(app)
    _request_and_verify(app, client)

    profile_page = client.get("/participant/profile")
    assert profile_page.status_code == 200
    assert b"Partecipa a un corso" in profile_page.data
    assert b'action="/participant/admissions"' in profile_page.data

    submitted = client.post("/participant/admissions", data={"code": code})
    assert submitted.status_code == 302
    assert submitted.headers["Location"].endswith("/participant/enroll/confirm")
    assert _pending_key(client) == course_id

    page = client.get("/participant/enroll/confirm")
    assert page.status_code == 200
    assert "Stai per iscriverti a: Radioprotezione".encode() in page.data
    assert b"Conferma e iscriviti" in page.data
    assert b'action="/participant/admissions"' not in page.data

    confirmed = client.post("/participant/enroll/confirm", data=_profile_payload())
    assert confirmed.status_code == 302
    assert confirmed.headers["Location"].endswith("/participant")
    assert "Iscrizione completata: puoi svolgere il questionario." in _flashes(client)
    assert _pending_key(client) is None
    with app.app_context():
        user = User.query.filter_by(email="persona@example.it").one()
        assert user.profile_completed
        enrollment = Enrollment.query.one()
        assert enrollment.course_id == course_id
        assert enrollment.participant_user_id == user.id


def test_self_enroll_accepts_lowercase_code(app, client):
    _, code = _course(app)
    _request_and_verify(app, client)

    typed = f"{code[:4]} {code[4:]}".lower()
    response = client.post("/participant/admissions", data={"code": typed})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/participant/enroll/confirm")


def test_flag_off_keeps_pending_request(app, client):
    course_id, code = _course(app, enabled=False)
    _request_and_verify(app, client)
    _complete_profile(client)

    response = client.post("/participant/admissions", data={"code": code})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/participant")
    with app.app_context():
        assert AdmissionRequest.query.one().status == "pending"
        assert Enrollment.query.count() == 0

    _set_course(app, course_id, status="in_progress")
    with app.app_context():
        AdmissionRequest.query.delete()
        db.session.commit()
    client.post("/participant/admissions", data={"code": code})
    assert GENERIC in _flashes(client)
    with app.app_context():
        assert AdmissionRequest.query.count() == 0


def test_flag_off_incomplete_profile_asks_profile_first(app, client):
    _, code = _course(app, enabled=False)
    _request_and_verify(app, client)

    response = client.post("/participant/admissions", data={"code": code})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/participant/profile")
    assert "Completa il profilo prima di chiedere l'ammissione." in _flashes(client)
    with app.app_context():
        assert AdmissionRequest.query.count() == 0


def _confirm_after_change(app, client, **fields):
    course_id, code = _course(app)
    _request_and_verify(app, client)
    client.post("/participant/admissions", data={"code": code})
    assert _pending_key(client) == course_id
    _set_course(app, course_id, **fields)
    response = client.post("/participant/enroll/confirm", data=_profile_payload())
    assert response.status_code == 302
    assert GENERIC in _flashes(client)
    assert _pending_key(client) is None
    with app.app_context():
        assert Enrollment.query.count() == 0
        user = User.query.filter_by(email="persona@example.it").one()
        assert not user.profile_completed


def test_confirm_rechecks_course_state_completed(app, client):
    _confirm_after_change(app, client, status="completed")


def test_confirm_rechecks_course_state_flag_off(app, client):
    _confirm_after_change(app, client, self_enrollment_enabled=False)


def test_confirm_does_not_overwrite_verified_company(app, client):
    _, code = _course(app)
    with app.app_context():
        db.session.add(
            Company(
                business_name="Originale Srl",
                vat_number="01234567897",
                address="Via Milano 2",
                postal_code="20100",
                city="Milano",
                email="info@originale.it",
                verification_status="verified",
            )
        )
        db.session.commit()
    _request_and_verify(app, client)
    client.post("/participant/admissions", data={"code": code})

    payload = _profile_payload(vat_number="01234567897", include_company=True)
    payload["company_business_name"] = "Hack Srl"
    response = client.post("/participant/enroll/confirm", data=payload)

    assert response.status_code == 302
    with app.app_context():
        company = Company.query.one()
        assert company.business_name == "Originale Srl"
        assert Enrollment.query.count() == 1


def test_confirm_invalid_vat_keeps_pending_course(app, client):
    course_id, code = _course(app)
    _request_and_verify(app, client)
    client.post("/participant/admissions", data={"code": code})

    response = client.post(
        "/participant/enroll/confirm", data=_profile_payload(vat_number="123")
    )

    assert response.status_code == 200
    assert "partita IVA italiana non".encode() in response.data
    assert "Stai per iscriverti a: Radioprotezione".encode() in response.data
    assert _enrollments(app) == 0
    assert _pending_key(client) == course_id


def test_profile_save_does_not_enroll_with_pending_code(app, client):
    _, code = _course(app)
    _request_and_verify(app, client)
    client.post("/participant/admissions", data={"code": code})

    response = client.post("/participant/profile", data=_profile_payload())

    assert response.status_code == 302
    assert _enrollments(app) == 0


def test_wrong_codes_throttle_and_audit(app, client):
    _course(app)
    _request_and_verify(app, client)
    _complete_profile(client)

    for typed in ("ZZZZ999999", "YYYY888888"):
        client.post("/participant/admissions", data={"code": typed})
        assert GENERIC in _flashes(client)

    client.post("/participant/admissions", data={"code": "XXXX777777"})
    assert "Troppi tentativi: riprova tra 2 secondi." in _flashes(client)
    with app.app_context():
        assert AdmissionRequest.query.count() == 0
        for event in AuditLog.query.all():
            text = str(event.detail or "")
            for typed in ("ZZZZ999999", "YYYY888888", "XXXX777777"):
                assert typed not in text


def test_valid_code_rejected_while_blocked(app, client):
    _, code = _course(app)
    _request_and_verify(app, client)

    client.post("/participant/admissions", data={"code": "ZZZZ999999"})
    client.post("/participant/admissions", data={"code": "YYYY888888"})
    response = client.post("/participant/admissions", data={"code": code})

    assert response.status_code == 302
    assert not response.headers["Location"].endswith("/participant/enroll/confirm")
    assert "Troppi tentativi: riprova tra 2 secondi." in _flashes(client)
    assert _pending_key(client) is None
    with app.app_context():
        assert AdmissionRequest.query.count() == 0


def test_already_enrolled_code_shows_message(app, client):
    _, code = _course(app)
    _request_and_verify(app, client)
    client.post("/participant/admissions", data={"code": code})
    client.post("/participant/enroll/confirm", data=_profile_payload())
    assert _enrollments(app) == 1
    _flashes(client)
    with client.session_transaction() as session:
        session.pop("_flashes", None)

    response = client.post("/participant/admissions", data={"code": code})

    assert response.status_code == 302
    assert not response.headers["Location"].endswith("/participant/enroll/confirm")
    assert "Sei già iscritto a questo corso." in _flashes(client)
    assert _pending_key(client) is None


def test_dashboard_highlights_code_box_without_active_courses(app, client):
    _, code = _course(app)
    _request_and_verify(app, client)
    _complete_profile(client)

    page = client.get("/participant").get_data(as_text=True)
    assert page.count("join-form") == 1
    assert "join-panel-highlight" in page
    assert "Inserisci il codice del corso" in page
    assert page.index("Inserisci il codice del corso") < page.index("Corsi e richieste")

    client.post("/participant/admissions", data={"code": code})
    client.post("/participant/enroll/confirm", data=_profile_payload())
    assert _enrollments(app) == 1

    page = client.get("/participant").get_data(as_text=True)
    assert page.count("join-form") == 1
    assert "join-panel-highlight" not in page
    assert "Inserisci il codice del corso" not in page
    assert page.index("Partecipa a un corso") < page.index("Corsi e richieste")


def test_dashboard_pending_request_hides_highlight(app, client):
    _, code = _course(app, enabled=False)
    _request_and_verify(app, client)
    _complete_profile(client)
    client.post("/participant/admissions", data={"code": code})

    page = client.get("/participant").get_data(as_text=True)
    assert "join-panel-highlight" not in page
    assert "Partecipa a un corso" in page
