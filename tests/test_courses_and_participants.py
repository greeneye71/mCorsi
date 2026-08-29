from __future__ import annotations

from datetime import date, time

from mcorsi.extensions import db
from mcorsi.models import AdmissionRequest, Company, Course, Employment, Enrollment, Role, User
from mcorsi.services.courses import create_course, request_admission


PASSWORD = "PasswordMoltoSicura1!"


def _make_user(app, email: str, role: str, *, first_name="", last_name="") -> str:
    with app.app_context():
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            profile_completed=role != "participant",
        )
        if role in {"admin", "operator"}:
            user.set_password(PASSWORD)
        user.roles.append(Role.query.filter_by(name=role).one())
        if role == "admin":
            user.roles.append(Role.query.filter_by(name="operator").one())
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, email: str):
    response = client.post("/auth/login", data={"email": email, "password": PASSWORD})
    assert response.status_code == 302


def _course_payload(referent_id: str, *, title="Radioprotezione", day="2026-09-20"):
    return {
        "title": title,
        "description": "Corso di aggiornamento professionale",
        "legal_references": "D.Lgs. 81/2008\nAccordo Stato-Regioni vigente",
        "topics": "Principi di prevenzione\nUso dei dispositivi di protezione",
        "status": "open",
        "referent_user_id": referent_id,
        "session_date": day,
        "start_time": "09:00",
        "end_time": "13:00",
        "delivery_mode": "online",
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "certificate_validity_months": "60",
    }


def test_full_operator_flow_and_clean_duplication(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin", first_name="Ada")
    _login(client, "admin@example.it")

    company_response = client.post(
        "/companies/new",
        data={
            "business_name": "Esempio Srl",
            "vat_number": "IT 01234567897",
            "tax_code": "01234567890",
            "address": "Via Roma 1",
            "postal_code": "00100",
            "city": "Roma",
            "province": "RM",
            "country": "IT",
            "email": "info@esempio.it",
            "pec": "",
            "verification_status": "verified",
        },
    )
    assert company_response.status_code == 302
    with app.app_context():
        company_id = Company.query.one().id

    participant_response = client.post(
        "/participants/new",
        data={
            "email": "partecipante@example.it",
            "first_name": "Mario",
            "last_name": "Rossi",
            "birth_place": "Roma",
            "birth_date": "1980-05-10",
            "tax_code": "RSSMRA80E10H501Z",
            "mobile_phone": "+39 333 1234567",
            "certificate_title": "Dott.",
            "company_id": company_id,
        },
    )
    assert participant_response.status_code == 302

    course_response = client.post("/courses/new", data=_course_payload(admin_id))
    assert course_response.status_code == 302
    with app.app_context():
        course = Course.query.one()
        course_id = course.id
        original_code = course.code
        assert len(original_code) == 10
        assert course.certificate_validity_months == 60
        assert "D.Lgs. 81/2008" in course.legal_references
        assert "Principi di prevenzione" in course.topics

    detail = client.get(f"/courses/{course_id}")
    assert detail.status_code == 200
    assert b"Riferimenti legislativi" in detail.data
    assert b"Principi di prevenzione" in detail.data

    requested = client.post(
        f"/courses/{course_id}/admissions", data={"email": "partecipante@example.it"}
    )
    assert requested.status_code == 302
    with app.app_context():
        admission_id = AdmissionRequest.query.one().id

    approved = client.post(
        f"/courses/{course_id}/admissions/{admission_id}/approve",
        data={"decision_message": "Benvenuto", "internal_note": "Verificato"},
    )
    assert approved.status_code == 302
    with app.app_context():
        assert AdmissionRequest.query.one().status == "approved"
        assert Enrollment.query.count() == 1

    duplicate_response = client.post(
        f"/courses/{course_id}/duplicate",
        data={
            "referent_user_id": admin_id,
            "session_date": "2027-01-15",
            "start_time": "14:00",
            "end_time": "18:00",
        },
    )
    assert duplicate_response.status_code == 302
    with app.app_context():
        courses = Course.query.order_by(Course.created_at).all()
        duplicate = courses[1]
        assert duplicate.code != original_code
        assert duplicate.status == "draft"
        assert duplicate.title == courses[0].title
        assert duplicate.legal_references == courses[0].legal_references
        assert duplicate.topics == courses[0].topics
        assert duplicate.admission_requests == []
        assert duplicate.enrollments == []


def test_only_referent_or_admin_can_decide(app, client):
    referent_id = _make_user(app, "referente@example.it", "operator")
    other_id = _make_user(app, "altro@example.it", "operator")
    participant_id = _make_user(app, "persona@example.it", "participant")
    with app.app_context():
        referent = db.session.get(User, referent_id)
        participant = db.session.get(User, participant_id)
        course = create_course(
            actor=referent,
            data={
                "title": "Sicurezza",
                "description": "",
                "status": "open",
                "referent_user_id": referent_id,
                "session_date": date(2026, 10, 1),
                "start_time": time(9, 0),
                "end_time": time(12, 0),
                "delivery_mode": "online",
                "meeting_url": "",
                "certificate_validity_months": 60,
            },
        )
        request = request_admission(course, participant, actor=participant)
        db.session.commit()
        course_id, admission_id = course.id, request.id

    _login(client, "altro@example.it")
    response = client.post(
        f"/courses/{course_id}/admissions/{admission_id}/approve",
        data={"decision_message": "", "internal_note": ""},
    )
    assert response.status_code == 403
    with app.app_context():
        assert db.session.get(AdmissionRequest, admission_id).status == "pending"
        assert Enrollment.query.count() == 0


def test_changing_company_preserves_employment_history(app, client):
    _make_user(app, "admin@example.it", "admin")
    participant_id = _make_user(app, "persona@example.it", "participant", first_name="Anna", last_name="Bianchi")
    with app.app_context():
        first = Company(
            business_name="Prima Srl", vat_number="11111111111", address="Via A 1",
            postal_code="00100", city="Roma", email="a@example.it", verification_status="verified",
        )
        second = Company(
            business_name="Seconda Srl", vat_number="22222222222", address="Via B 2",
            postal_code="20100", city="Milano", email="b@example.it", verification_status="verified",
        )
        db.session.add_all([first, second])
        db.session.commit()
        first_id, second_id = first.id, second.id

    _login(client, "admin@example.it")
    base_data = {
        "email": "persona@example.it",
        "first_name": "Anna",
        "last_name": "Bianchi",
        "birth_place": "Milano",
        "birth_date": "1990-01-02",
        "tax_code": "",
        "mobile_phone": "",
        "certificate_title": "",
    }
    assert client.post(
        f"/participants/{participant_id}/edit", data={**base_data, "company_id": first_id}
    ).status_code == 302
    assert client.post(
        f"/participants/{participant_id}/edit", data={**base_data, "company_id": second_id}
    ).status_code == 302

    with app.app_context():
        employments = Employment.query.filter_by(participant_user_id=participant_id).all()
        assert len(employments) == 2
        old = next(item for item in employments if item.company_id == first_id)
        current = next(item for item in employments if item.company_id == second_id)
        assert old.is_current is False and old.ended_on is not None
        assert current.is_current is True and current.ended_on is None


def test_course_rejects_end_time_before_start(app, client):
    admin_id = _make_user(app, "admin@example.it", "admin")
    _login(client, "admin@example.it")
    response = client.post(
        "/courses/new",
        data={**_course_payload(admin_id), "start_time": "15:00", "end_time": "14:00"},
    )
    assert response.status_code == 200
    assert b"successiva" in response.data
    with app.app_context():
        assert Course.query.count() == 0
