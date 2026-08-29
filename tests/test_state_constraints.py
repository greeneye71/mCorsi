import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from mcorsi.extensions import db


EXPECTED_CHECKS = {
    "email_outbox": {"ck_email_outbox_status"},
    "companies": {"ck_companies_verification_status", "ck_companies_source"},
    "employments": {"ck_employments_verification_status"},
    "courses": {"ck_courses_status", "ck_courses_delivery_mode"},
    "admission_requests": {"ck_admission_requests_status"},
    "enrollments": {"ck_enrollments_attendance_status"},
    "certificates": {
        "ck_certificates_source",
        "ck_certificates_verification_status",
        "ck_certificates_status",
    },
    "import_batches": {"ck_import_batches_status"},
    "import_rows": {"ck_import_rows_status"},
    "questions": {"ck_questions_response_type"},
}


def test_all_categorical_state_constraints_are_created(app):
    with app.app_context():
        inspector = sa.inspect(db.engine)
        for table_name, expected_names in EXPECTED_CHECKS.items():
            actual_names = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            assert expected_names <= actual_names


def test_database_rejects_an_unknown_email_status(app):
    with app.app_context():
        with pytest.raises(IntegrityError, match="ck_email_outbox_status"):
            db.session.execute(
                sa.text(
                    "INSERT INTO email_outbox "
                    "(id, message_type, recipient_email, subject, text_body, status, attempts, "
                    "max_attempts, next_attempt_at, last_error, related_type, related_id, created_at) "
                    "VALUES ('invalid-state', 'test', 'test@example.it', 'test', 'test', "
                    "'unknown', 0, 1, CURRENT_TIMESTAMP, '', '', '', CURRENT_TIMESTAMP)"
                )
            )
