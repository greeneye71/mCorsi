"""Regressioni dei rilievi dell'audit del 10/10/2026."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from mcorsi.extensions import db
from mcorsi.models import AuditLog, Company, CompanyContact, OneTimeCode, Role, User
from mcorsi.services.courses import create_course
from mcorsi.services.mcp_access import create_access_token, verify_access_token
from mcorsi.services.otp import _consume, request_company_code


PASSWORD = "PasswordMoltoSicura1!"


def _admin() -> User:
    user = User(email="admin@example.it", first_name="Ada", profile_completed=True)
    user.set_password(PASSWORD)
    user.roles.extend(
        [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
    )
    db.session.add(user)
    db.session.flush()
    return user


def _course(admin: User, title: str, day: date):
    return create_course(
        actor=admin,
        data={
            "title": title,
            "description": "",
            "status": "open",
            "referent_user_id": admin.id,
            "session_date": day,
            "start_time": time(9),
            "end_time": time(13),
            "delivery_mode": "online",
            "meeting_url": "",
            "certificate_validity_months": 60,
        },
    )


def _company(**overrides) -> Company:
    data = {
        "business_name": "Azienda Srl",
        "vat_number": "01234567890",
        "address": "Via Roma 1",
        "postal_code": "00100",
        "city": "Roma",
        "email": "azienda@example.it",
        "verification_status": "verified",
    }
    data.update(overrides)
    company = Company(**data)
    db.session.add(company)
    db.session.flush()
    return company


def _login_as(client, auth_id: str) -> None:
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = auth_id
        browser_session["_fresh"] = True


def test_s01_password_change_invalidates_existing_sessions(app, client):
    with app.app_context():
        admin = _admin()
        db.session.commit()
        admin_id = admin.id
        old_auth_id = admin.get_id()
    _login_as(client, old_auth_id)
    assert client.get("/").status_code == 200
    with app.app_context():
        admin = db.session.get(User, admin_id)
        admin.set_password("UnAltraPasswordSicura2!")
        db.session.commit()
        assert admin.get_id() != old_auth_id
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_s01_disabled_user_loses_existing_sessions(app, client):
    with app.app_context():
        admin = _admin()
        db.session.commit()
        admin_id = admin.id
        old_auth_id = admin.get_id()
    _login_as(client, old_auth_id)
    with app.app_context():
        admin = db.session.get(User, admin_id)
        admin.is_active = False
        admin.revoke_sessions()
        admin.is_active = True
        db.session.commit()
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_s02_mcp_token_requires_active_admin_owner(app):
    with app.app_context():
        admin = _admin()
        raw_token, _access = create_access_token(
            name="Agente", scopes=["courses:read"], creator=admin, expires_at=None
        )
        db.session.commit()
        assert verify_access_token(raw_token, update_last_used=False) is not None

        admin.is_active = False
        db.session.commit()
        assert verify_access_token(raw_token, update_last_used=False) is None

        admin.is_active = True
        admin.roles = [Role.query.filter_by(name="operator").one()]
        db.session.commit()
        assert verify_access_token(raw_token, update_last_used=False) is None


def test_s03_one_time_code_is_consumed_only_once(app, client):
    client.post("/participant/access", data={"email": "persona@example.it"})
    with app.app_context():
        challenge = OneTimeCode.query.one()
        now = datetime.now(timezone.utc)
        assert _consume(challenge.id, now) is True
        assert _consume(challenge.id, now) is False


def test_s07_company_name_is_escaped_in_otp_email(app):
    with app.app_context():
        _company(business_name="<script>alert(1)</script> Srl")
        db.session.commit()
        assert request_company_code("azienda@example.it", "01234567890") is not None
        html_body = app.config["MAIL_OUTBOX"][-1]["html_body"]
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body


def test_b01_inactive_contact_gets_no_challenge(app):
    with app.app_context():
        company = _company()
        user = User(email="azienda@example.it", profile_completed=True)
        user.roles.append(Role.query.filter_by(name="company_contact").one())
        db.session.add(user)
        db.session.flush()
        db.session.add(CompanyContact(company=company, user=user, is_active=False))
        db.session.commit()
        assert request_company_code("azienda@example.it", "01234567890") is None
        assert OneTimeCode.query.count() == 0
        assert app.config["MAIL_OUTBOX"] == []


def test_b02_participant_with_company_role_lands_on_participant_portal(app, client):
    with app.app_context():
        user = User(email="persona@example.it", first_name="Mario", profile_completed=True)
        user.roles.extend(
            [
                Role.query.filter_by(name="participant").one(),
                Role.query.filter_by(name="company_contact").one(),
            ]
        )
        db.session.add(user)
        db.session.commit()
        auth_id = user.get_id()
    _login_as(client, auth_id)
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/participant")


def test_b05_upcoming_filter_applies_before_limit(app):
    from mcorsi.services.mcp_tools import list_courses_data

    with app.app_context():
        admin = _admin()
        upcoming = _course(admin, "Futuro", date.today() + timedelta(days=30))
        db.session.flush()
        upcoming.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        for index in range(3):
            _course(admin, f"Passato {index}", date.today() - timedelta(days=30 + index))
        db.session.commit()
        result = list_courses_data(upcoming_only=True, limit=1)
        assert [item["title"] for item in result["courses"]] == ["Futuro"]


def test_b10_course_creation_audit_has_target(app):
    with app.app_context():
        admin = _admin()
        course = _course(admin, "Radioprotezione", date.today() + timedelta(days=10))
        db.session.commit()
        event = AuditLog.query.filter_by(event_type="course.created").one()
        assert event.target_id == course.id


def test_s06_pdf_is_parsed_in_a_bounded_child_process(tmp_path):
    from io import BytesIO

    import pytest
    from reportlab.pdfgen import canvas

    from mcorsi.services.pdf_probe import PdfProbeError, count_pdf_pages

    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 760, "Attestato")
    document.showPage()
    document.save()
    valid = tmp_path / "valido.pdf"
    valid.write_bytes(output.getvalue())
    assert count_pdf_pages(valid) == 1

    broken = tmp_path / "rotto.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"\x00" * 64)
    with pytest.raises(PdfProbeError):
        count_pdf_pages(broken)

    with pytest.raises(PdfProbeError, match="timeout"):
        count_pdf_pages(valid, timeout=0.001)
