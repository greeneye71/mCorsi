from __future__ import annotations

from datetime import date, time, timedelta

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
        assert result == {"sent": 1, "failed": 0, "deferred": 0}
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
