from __future__ import annotations

import re
from datetime import date, time

import pytest

from mcorsi import create_app
from mcorsi.extensions import db
from mcorsi.models import AdmissionRequest, Company, OneTimeCode, Role, SmtpConfiguration, User
from mcorsi.services.courses import create_course
from mcorsi.services.secrets import decrypt_secret


PASSWORD = "PasswordMoltoSicura1!"


def _admin(app, email="admin@example.it") -> str:
    with app.app_context():
        user = User(email=email, first_name="Ada", profile_completed=True)
        user.set_password(PASSWORD)
        user.roles.extend(
            [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def _extract_code(app) -> str:
    message = app.config["MAIL_OUTBOX"][-1]
    match = re.search(r"\b(\d{6})\b", message["text_body"])
    assert match
    return match.group(1)


def _request_and_verify(app, client, email="persona@example.it") -> str:
    response = client.post("/participant/access", data={"email": email})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/participant/verify")
    code = _extract_code(app)
    verified = client.post("/participant/verify", data={"code": code})
    assert verified.status_code == 302
    assert verified.headers["Location"].endswith("/participant/profile")
    return code


def _profile_payload(*, vat_number="", include_company=False):
    data = {
        "first_name": "Mario",
        "last_name": "Rossi",
        "birth_place": "Roma",
        "birth_date": "1980-05-10",
        "tax_code": "RSSMRA80E10H501Z",
        "mobile_phone": "+39 333 1234567",
        "certificate_title": "Dott.",
        "vat_number": vat_number,
        "company_business_name": "",
        "company_tax_code": "",
        "company_address": "",
        "company_postal_code": "",
        "company_city": "",
        "company_province": "",
        "company_country": "IT",
        "company_email": "",
        "company_pec": "",
    }
    if include_company:
        data.update(
            {
                "company_business_name": "Nuova Azienda Srl",
                "company_tax_code": "01234567890",
                "company_address": "Via Roma 1",
                "company_postal_code": "00100",
                "company_city": "Roma",
                "company_province": "RM",
                "company_email": "info@nuovaazienda.it",
            }
        )
    return data


def test_otp_profile_company_and_course_request(app, client):
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
            },
        )
        db.session.commit()
        course_code = course.code

    code = _request_and_verify(app, client)
    with app.app_context():
        challenge = OneTimeCode.query.one()
        user = User.query.filter_by(email="persona@example.it").one()
        assert code not in challenge.code_hash
        assert challenge.consumed_at is not None
        assert user.has_role("participant")
        assert not user.profile_completed

    saved = client.post(
        "/participant/profile",
        data=_profile_payload(vat_number="IT 01234567890", include_company=True),
    )
    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("/participant")
    with app.app_context():
        company = Company.query.one()
        assert company.vat_number == "IT01234567890"
        assert company.verification_status == "pending"
        assert company.source == "participant"

    requested = client.post("/participant/admissions", data={"code": course_code.lower()})
    assert requested.status_code == 302
    with app.app_context():
        admission = AdmissionRequest.query.one()
        assert admission.status == "pending"
        assert admission.course.code == course_code

    assert client.get("/courses").status_code == 403


def test_otp_is_single_use_and_resend_is_limited(app, client):
    first = client.post("/participant/access", data={"email": "persona@example.it"})
    assert first.status_code == 302
    code = _extract_code(app)
    assert len(app.config["MAIL_OUTBOX"]) == 1

    limited = client.post("/participant/access", data={"email": "persona@example.it"})
    assert limited.status_code == 200
    assert len(app.config["MAIL_OUTBOX"]) == 1
    assert b"Attendi" in limited.data

    assert client.post("/participant/verify", data={"code": code}).status_code == 302
    client.post("/auth/logout")
    with app.app_context():
        challenge = OneTimeCode.query.one()
        assert challenge.consumed_at is not None


def test_participant_otp_never_authenticates_staff_account(app, client):
    admin_id = _admin(app, email="staff-otp@example.it")

    response = client.post("/participant/access", data={"email": "staff-otp@example.it"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/participant/verify")
    assert app.config["MAIL_OUTBOX"] == []
    with app.app_context():
        assert OneTimeCode.query.count() == 0
        admin = db.session.get(User, admin_id)
        assert admin.has_role("admin", "operator")
        assert not admin.has_role("participant")


def test_five_wrong_codes_invalidate_challenge(app, client):
    client.post("/participant/access", data={"email": "persona@example.it"})
    correct = _extract_code(app)
    for _ in range(5):
        response = client.post("/participant/verify", data={"code": "000000" if correct != "000000" else "111111"})
        assert response.status_code == 200
    response = client.post("/participant/verify", data={"code": correct})
    assert response.status_code == 200
    with app.app_context():
        challenge = OneTimeCode.query.one()
        assert challenge.attempts == 5
        assert challenge.consumed_at is not None


def test_smtp_password_is_encrypted_and_test_mail_is_sent(app, client):
    _admin(app)
    assert client.post(
        "/auth/login", data={"email": "admin@example.it", "password": PASSWORD}
    ).status_code == 302
    response = client.post(
        "/settings/smtp",
        data={
            "host": "smtp.example.it",
            "port": "587",
            "username": "mailer@example.it",
            "password": "SegretoSmtp!",
            "from_email": "corsi@example.it",
            "from_name": "Ufficio corsi",
            "use_starttls": "y",
            "timeout_seconds": "20",
            "test_recipient": "admin@example.it",
            "save_and_test": "1",
        },
    )
    assert response.status_code == 302
    assert len(app.config["MAIL_OUTBOX"]) == 1
    with app.app_context():
        configuration = db.session.get(SmtpConfiguration, 1)
        assert configuration.password_encrypted != "SegretoSmtp!"
        assert "SegretoSmtp!" not in configuration.password_encrypted
        assert decrypt_secret(configuration.password_encrypted) == "SegretoSmtp!"


def test_remote_smtp_requires_transport_encryption(app, client):
    _admin(app)
    client.post(
        "/auth/login", data={"email": "admin@example.it", "password": PASSWORD}
    )
    response = client.post(
        "/settings/smtp",
        data={
            "host": "smtp.example.it",
            "port": "25",
            "from_email": "corsi@example.it",
            "from_name": "Ufficio corsi",
            "timeout_seconds": "20",
            "save": "1",
        },
    )
    assert response.status_code == 200
    assert b"STARTTLS" in response.data
    with app.app_context():
        assert db.session.get(SmtpConfiguration, 1) is None


def test_existing_company_needs_only_vat_number(app, client):
    with app.app_context():
        company = Company(
            business_name="Esistente Srl",
            vat_number="01234567890",
            address="Via Milano 2",
            postal_code="20100",
            city="Milano",
            email="info@esistente.it",
            verification_status="verified",
        )
        db.session.add(company)
        db.session.commit()
        company_id = company.id
    _request_and_verify(app, client)
    response = client.post(
        "/participant/profile", data=_profile_payload(vat_number="01234567890")
    )
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email="persona@example.it").one()
        assert user.participant_profile.current_employment.company_id == company_id
        assert Company.query.count() == 1


def test_production_rejects_reused_or_default_keys():
    with pytest.raises(RuntimeError, match="MCORSI_SECRET_KEY"):
        create_app(
            "production",
            {
                "SECRET_KEY": "development-only-change-me",
                "ENCRYPTION_KEY": "development-only-change-me",
                "OTP_PEPPER": "development-only-change-me",
            },
        )
