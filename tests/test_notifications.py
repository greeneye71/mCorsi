from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from mcorsi.extensions import db
from mcorsi.models import EmailOutbox, Enrollment, NotificationConfiguration, Role, User
from mcorsi.services.courses import create_course
from mcorsi.services.notifications import deliver_pending, enqueue_reminders


def _data():
    admin = User(email="admin@example.it", profile_completed=True)
    admin.roles.extend(
        [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
    )
    participant = User(
        email="persona@example.it", first_name="Mario", last_name="Rossi", profile_completed=True
    )
    participant.roles.append(Role.query.filter_by(name="participant").one())
    db.session.add_all([admin, participant])
    db.session.flush()
    target = date.today() + timedelta(days=3)
    course = create_course(
        actor=admin,
        data={
            "title": "Radioprotezione",
            "description": "",
            "status": "open",
            "referent_user_id": admin.id,
            "session_date": target,
            "start_time": time(9),
            "end_time": time(13),
            "delivery_mode": "online",
            "meeting_url": "",
            "certificate_validity_months": 60,
        },
    )
    db.session.add(Enrollment(course=course, participant=participant))
    db.session.add(
        NotificationConfiguration(
            id=1,
            course_reminders_enabled=True,
            course_reminder_days=3,
            certificate_reminders_enabled=True,
            certificate_expiry_days=180,
            updated_by_user_id=admin.id,
        )
    )
    db.session.commit()


def test_reminders_are_idempotent_and_delivered_from_outbox(app):
    with app.app_context():
        _data()
        first = enqueue_reminders()
        second = enqueue_reminders()
        assert first["course"] == 1
        assert second["course"] == 0
        assert EmailOutbox.query.count() == 1
        result = deliver_pending()
        assert result == {"sent": 1, "failed": 0, "deferred": 0, "canceled": 0}
        message = EmailOutbox.query.one()
        assert message.status == "sent"
        assert app.config["MAIL_OUTBOX"][0]["recipient"] == "persona@example.it"


def test_temporary_mail_failure_is_deferred(app):
    with app.app_context():
        _data()
        enqueue_reminders()
        app.config["MAIL_BACKEND"] = "smtp"
        result = deliver_pending()
        assert result["deferred"] == 1
        message = EmailOutbox.query.one()
        assert message.status == "pending"
        assert message.attempts == 1
        assert message.last_error == "Invio non riuscito; consultare il log del server."


def _certificate_for_company(app, verification_status: str) -> str:
    from mcorsi.models import Certificate, Company
    from mcorsi.services.storage import save_bytes

    _data()
    admin = User.query.filter_by(email="admin@example.it").one()
    participant = User.query.filter_by(email="persona@example.it").one()
    company = Company(
        business_name="Azienda Srl",
        vat_number="01234567890",
        address="Via Roma 1",
        postal_code="00100",
        city="Roma",
        email="azienda@example.it",
        verification_status=verification_status,
    )
    from io import BytesIO

    from reportlab.pdfgen import canvas

    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 760, "Attestato")
    document.showPage()
    document.save()
    pdf = save_bytes(
        output.getvalue(),
        filename="attestato.pdf",
        mime_type="application/pdf",
        actor=admin,
        category="certificates",
    )
    certificate = Certificate(
        participant=participant,
        company=company,
        pdf_file=pdf,
        title_snapshot="Antincendio",
        course_date=date.today() - timedelta(days=300),
        expires_at=date.today() + timedelta(days=30),
        source="participant_upload",
        verification_status="verified",
    )
    db.session.add_all([company, certificate])
    db.session.commit()
    return company.id


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_unverified_company_receives_no_expiry_notice(app, status):
    with app.app_context():
        _certificate_for_company(app, status)
        counts = enqueue_reminders()
        assert counts["certificate_company"] == 0
        assert EmailOutbox.query.filter_by(message_type="certificate_expiry_company").count() == 0


def test_queued_company_notice_is_canceled_after_downgrade(app):
    from mcorsi.models import Company

    with app.app_context():
        company_id = _certificate_for_company(app, "verified")
        assert enqueue_reminders()["certificate_company"] == 1
        db.session.get(Company, company_id).verification_status = "rejected"
        db.session.commit()
        result = deliver_pending()
        assert result["canceled"] == 1
        message = EmailOutbox.query.filter_by(message_type="certificate_expiry_company").one()
        assert message.status == "failed"
        recipients = [item["recipient"] for item in app.config["MAIL_OUTBOX"]]
        assert "azienda@example.it" not in recipients


def test_only_one_worker_claims_a_message_and_lease_expires(app):
    from datetime import datetime, timezone

    from mcorsi.services.notifications import DELIVERY_LEASE, _claim

    with app.app_context():
        _data()
        enqueue_reminders()
        message_id = EmailOutbox.query.one().id
        now = datetime.now(timezone.utc)
        assert _claim(message_id, now) is True
        assert _claim(message_id, now) is False
        assert deliver_pending(now=now)["sent"] == 0
        later = now + DELIVERY_LEASE + timedelta(seconds=1)
        assert deliver_pending(now=later)["sent"] == 1
        assert len(app.config["MAIL_OUTBOX"]) == 1
