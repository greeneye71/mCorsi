from __future__ import annotations

import re
from datetime import date
from io import BytesIO

from reportlab.pdfgen import canvas

from mcorsi.extensions import db
from mcorsi.models import Certificate, Company, CompanyContact, ParticipantProfile, Role, User
from mcorsi.services.storage import save_bytes


def _pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 760, "Attestato verificato")
    document.showPage()
    document.save()
    return output.getvalue()


def _setup(app):
    with app.app_context():
        uploader = User(email="admin@example.it", profile_completed=True)
        uploader.roles.extend(
            [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
        )
        company = Company(
            business_name="Studio Esempio Srl",
            vat_number="01234567890",
            address="Via Roma 1",
            postal_code="00100",
            city="Roma",
            email="formazione@esempio.it",
            verification_status="verified",
        )
        other_company = Company(
            business_name="Altra Srl",
            vat_number="99999999999",
            address="Via Milano 1",
            postal_code="20100",
            city="Milano",
            email="info@altra.it",
            verification_status="verified",
        )
        participant = User(
            email="dipendente@example.it",
            first_name="Mario",
            last_name="Rossi",
            profile_completed=True,
        )
        participant.roles.append(Role.query.filter_by(name="participant").one())
        participant.participant_profile = ParticipantProfile(
            birth_place="Roma", birth_date=date(1980, 1, 1)
        )
        db.session.add_all([uploader, company, other_company, participant])
        db.session.flush()
        first_pdf = save_bytes(
            _pdf(), filename="radioprotezione.pdf", mime_type="application/pdf", actor=uploader, category="certificates"
        )
        second_pdf = save_bytes(
            _pdf(), filename="altro.pdf", mime_type="application/pdf", actor=uploader, category="certificates"
        )
        visible = Certificate(
            participant=participant,
            company=company,
            pdf_file=first_pdf,
            title_snapshot="Radioprotezione",
            course_date=date(2026, 3, 1),
            expires_at=date(2031, 3, 1),
            source="participant_upload",
            verification_status="verified",
        )
        hidden = Certificate(
            participant=participant,
            company=other_company,
            pdf_file=second_pdf,
            title_snapshot="Altro corso",
            course_date=date(2026, 2, 1),
            source="participant_upload",
            verification_status="verified",
        )
        db.session.add_all([visible, hidden])
        db.session.commit()
        return visible.id, hidden.id


def test_verified_company_uses_otp_and_only_sees_its_certificates(app, client):
    visible_id, hidden_id = _setup(app)
    requested = client.post(
        "/company/access",
        data={"email": "formazione@esempio.it", "vat_number": "IT 01234567890"},
    )
    assert requested.status_code == 302
    message = app.config["MAIL_OUTBOX"][-1]
    code = re.search(r"\b(\d{6})\b", message["text_body"]).group(1)
    verified = client.post("/company/verify", data={"code": code})
    assert verified.status_code == 302
    assert verified.headers["Location"].endswith("/company")
    dashboard = client.get("/company")
    assert dashboard.status_code == 200
    assert b"Radioprotezione" in dashboard.data
    assert b"Altro corso" not in dashboard.data
    assert client.get(f"/documents/certificates/{visible_id}/download").status_code == 200
    assert client.get(f"/documents/certificates/{hidden_id}/download").status_code == 403


def test_unknown_or_unverified_company_does_not_receive_email(app, client):
    _setup(app)
    before = len(app.config["MAIL_OUTBOX"])
    response = client.post(
        "/company/access",
        data={"email": "formazione@esempio.it", "vat_number": "00000000000"},
    )
    assert response.status_code == 302
    assert len(app.config["MAIL_OUTBOX"]) == before


def test_revoked_company_contact_cannot_download_from_existing_session(app, client):
    visible_id, _hidden_id = _setup(app)
    client.post(
        "/company/access",
        data={"email": "formazione@esempio.it", "vat_number": "01234567890"},
    )
    code = re.search(r"\b(\d{6})\b", app.config["MAIL_OUTBOX"][-1]["text_body"]).group(1)
    client.post("/company/verify", data={"code": code})
    with app.app_context():
        contact = CompanyContact.query.one()
        contact.is_active = False
        db.session.commit()
    assert client.get(f"/documents/certificates/{visible_id}/download").status_code == 403
