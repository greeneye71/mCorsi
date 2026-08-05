from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape

from ..extensions import db
from ..models import Certificate, EmailOutbox, Enrollment, NotificationConfiguration
from .mail import MailConfigurationError, MailDeliveryError, send_email
from .certificates import course_date
from .secrets import SecretDecryptionError


def configuration() -> NotificationConfiguration | None:
    return db.session.get(NotificationConfiguration, 1)


def queue_email(
    *,
    message_type: str,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    related_type: str = "",
    related_id: str = "",
    unique_key: str | None = None,
) -> EmailOutbox | None:
    if unique_key and EmailOutbox.query.filter_by(unique_key=unique_key).first():
        return None
    message = EmailOutbox(
        message_type=message_type,
        recipient_email=recipient.strip().casefold(),
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        related_type=related_type,
        related_id=related_id,
        unique_key=unique_key,
    )
    db.session.add(message)
    db.session.flush()
    return message


def enqueue_reminders(today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    settings = configuration()
    if settings is None:
        return {"course": 0, "certificate_participant": 0, "certificate_company": 0}
    counts = {"course": 0, "certificate_participant": 0, "certificate_company": 0}
    if settings.course_reminders_enabled:
        target = today + timedelta(days=settings.course_reminder_days)
        for enrollment in Enrollment.query.all():
            course = enrollment.course
            session = course.first_session
            if (
                not session
                or course_date(course) != target
                or course.status in {"canceled", "archived"}
                or enrollment.attendance_status == "absent"
            ):
                continue
            participant = enrollment.participant
            queued = queue_email(
                message_type="course_reminder",
                recipient=participant.email,
                subject=f"Promemoria corso: {course.title}",
                text_body=(
                    f"Ciao {participant.first_name or participant.display_name},\n\n"
                    f"ti ricordiamo il corso “{course.title}” del {target.strftime('%d/%m/%Y')}.\n"
                    "Accedi a mCorsi per i dettagli e i documenti."
                ),
                html_body=(
                    f"<p>Ciao {escape(participant.first_name or participant.display_name)},</p>"
                    f"<p>ti ricordiamo il corso <strong>{escape(course.title)}</strong> del {target.strftime('%d/%m/%Y')}.</p>"
                    "<p>Accedi a mCorsi per i dettagli e i documenti.</p>"
                ),
                related_type="enrollment",
                related_id=enrollment.id,
                unique_key=f"course:{enrollment.id}:{target.isoformat()}",
            )
            counts["course"] += bool(queued)
    if settings.certificate_reminders_enabled:
        limit = today + timedelta(days=settings.certificate_expiry_days)
        certificates = Certificate.query.filter(
            Certificate.status == "valid",
            Certificate.verification_status == "verified",
            Certificate.expires_at.is_not(None),
            Certificate.expires_at >= today,
            Certificate.expires_at <= limit,
        ).all()
        for certificate in certificates:
            participant = certificate.participant
            expiry = certificate.expires_at.strftime("%d/%m/%Y")
            queued = queue_email(
                message_type="certificate_expiry",
                recipient=participant.email,
                subject=f"Attestato in scadenza: {certificate.title_snapshot}",
                text_body=(
                    f"Ciao {participant.first_name or participant.display_name},\n\n"
                    f"l'attestato “{certificate.title_snapshot}” scadrà il {expiry}."
                ),
                related_type="certificate",
                related_id=certificate.id,
                unique_key=f"certificate:{certificate.id}:participant:{certificate.expires_at.isoformat()}",
            )
            counts["certificate_participant"] += bool(queued)
            if certificate.company and certificate.company.email:
                queued = queue_email(
                    message_type="certificate_expiry_company",
                    recipient=certificate.company.email,
                    subject=f"Attestato dipendente in scadenza: {participant.display_name}",
                    text_body=(
                        f"L'attestato “{certificate.title_snapshot}” di {participant.display_name} "
                        f"scadrà il {expiry}. Accedi all'area azienda mCorsi per scaricarlo."
                    ),
                    related_type="certificate",
                    related_id=certificate.id,
                    unique_key=f"certificate:{certificate.id}:company:{certificate.expires_at.isoformat()}",
                )
                counts["certificate_company"] += bool(queued)
    db.session.commit()
    return counts


def deliver_pending(limit: int = 50, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    messages = (
        EmailOutbox.query.filter(
            EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= now
        )
        .order_by(EmailOutbox.created_at)
        .limit(limit)
        .all()
    )
    result = {"sent": 0, "failed": 0, "deferred": 0}
    for message in messages:
        try:
            send_email(
                recipient=message.recipient_email,
                subject=message.subject,
                text_body=message.text_body,
                html_body=message.html_body,
            )
            message.status = "sent"
            message.sent_at = now
            message.last_error = ""
            result["sent"] += 1
        except (MailConfigurationError, MailDeliveryError, SecretDecryptionError) as exc:
            message.attempts += 1
            message.last_error = str(exc)[:1000]
            if message.attempts >= message.max_attempts:
                message.status = "failed"
                result["failed"] += 1
            else:
                delay_minutes = min(240, 2 ** message.attempts * 5)
                message.next_attempt_at = now + timedelta(minutes=delay_minutes)
                result["deferred"] += 1
        db.session.commit()
    return result
