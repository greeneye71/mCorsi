"""iscrizione diretta con codice

Revision ID: a7c3e9d1b4f6
Revises: f3b9c1d7e5a2
Create Date: 2026-11-14 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "a7c3e9d1b4f6"
down_revision = "f3b9c1d7e5a2"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotente: su SQLite il DDL non è transazionale, quindi un tentativo
    # precedente interrotto può aver già aggiunto la colonna o la tabella.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "_alembic_tmp_courses" in tables:
        if "courses" not in tables:
            raise RuntimeError(
                "Migrazione interrotta: tabella courses assente e _alembic_tmp_courses "
                "presente. Ripristinare un backup prima di riprovare."
            )
        op.drop_table("_alembic_tmp_courses")

    columns = {column["name"] for column in inspector.get_columns("courses")}
    if "self_enrollment_enabled" not in columns:
        with op.batch_alter_table("courses") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "self_enrollment_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    if "course_code_failures" not in tables:
        op.create_table(
            "course_code_failures",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("scope", sa.String(length=8), nullable=False),
            sa.Column("subject", sa.String(length=64), nullable=False),
            sa.Column("failures", sa.Integer(), nullable=False),
            sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "scope", "subject", name="uq_course_code_failures_scope_subject"
            ),
            sa.CheckConstraint(
                "scope IN ('user', 'ip')", name="ck_course_code_failures_scope"
            ),
        )
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.7.0', "
            "database_version = 8, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "course_code_failures" in tables:
        op.drop_table("course_code_failures")
    columns = {column["name"] for column in inspector.get_columns("courses")}
    if "self_enrollment_enabled" in columns:
        with op.batch_alter_table("courses") as batch_op:
            batch_op.drop_column("self_enrollment_enabled")
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.6.0', "
            "database_version = 7, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
