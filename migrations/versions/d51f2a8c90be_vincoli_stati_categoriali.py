"""vincoli stati categoriali

Revision ID: d51f2a8c90be
Revises: c74d1f83a602
Create Date: 2026-08-29 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "d51f2a8c90be"
down_revision = "c74d1f83a602"
branch_labels = None
depends_on = None


CONSTRAINTS = {
    "email_outbox": (
        ("ck_email_outbox_status", "status", ("pending", "sent", "failed")),
    ),
    "companies": (
        (
            "ck_companies_verification_status",
            "verification_status",
            ("pending", "verified", "rejected"),
        ),
        ("ck_companies_source", "source", ("operator", "participant")),
    ),
    "employments": (
        (
            "ck_employments_verification_status",
            "verification_status",
            ("pending", "verified", "rejected"),
        ),
    ),
    "courses": (
        (
            "ck_courses_status",
            "status",
            ("draft", "open", "in_progress", "completed", "canceled", "archived"),
        ),
        (
            "ck_courses_delivery_mode",
            "delivery_mode",
            ("online", "in_person", "hybrid"),
        ),
    ),
    "admission_requests": (
        (
            "ck_admission_requests_status",
            "status",
            ("pending", "approved", "rejected"),
        ),
    ),
    "enrollments": (
        (
            "ck_enrollments_attendance_status",
            "attendance_status",
            ("pending", "attended", "absent"),
        ),
    ),
    "certificates": (
        (
            "ck_certificates_source",
            "source",
            ("generated", "participant_upload"),
        ),
        (
            "ck_certificates_verification_status",
            "verification_status",
            ("pending", "verified"),
        ),
        ("ck_certificates_status", "status", ("valid",)),
    ),
    "import_batches": (
        (
            "ck_import_batches_status",
            "status",
            ("preview", "completed", "completed_with_errors"),
        ),
    ),
    "import_rows": (
        (
            "ck_import_rows_status",
            "status",
            ("ready", "error", "skipped", "imported"),
        ),
    ),
    "questions": (
        (
            "ck_questions_response_type",
            "response_type",
            ("single", "multiple"),
        ),
    ),
}


def _sql_list(values):
    return ", ".join(f"'{value}'" for value in values)


def _reject_unknown_values():
    connection = op.get_bind()
    for table_name, constraints in CONSTRAINTS.items():
        for _, column_name, allowed_values in constraints:
            query = sa.text(
                f"SELECT DISTINCT {column_name} FROM {table_name} "
                f"WHERE {column_name} NOT IN ({_sql_list(allowed_values)})"
            )
            invalid_values = connection.execute(query).scalars().all()
            if invalid_values:
                values = ", ".join(sorted(repr(value) for value in invalid_values))
                raise RuntimeError(
                    f"Migrazione interrotta: {table_name}.{column_name} "
                    f"contiene valori non riconosciuti: {values}"
                )


def upgrade():
    _reject_unknown_values()

    for table_name, constraints in CONSTRAINTS.items():
        with op.batch_alter_table(table_name) as batch_op:
            for constraint_name, column_name, allowed_values in constraints:
                batch_op.create_check_constraint(
                    constraint_name,
                    f"{column_name} IN ({_sql_list(allowed_values)})",
                )

    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.9', "
            "database_version = 6, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    for table_name, constraints in reversed(CONSTRAINTS.items()):
        with op.batch_alter_table(table_name) as batch_op:
            for constraint_name, _, _ in constraints:
                batch_op.drop_constraint(constraint_name, type_="check")

    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.8', "
            "database_version = 5, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
