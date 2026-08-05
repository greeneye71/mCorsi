"""corsi storici senza questionario

Revision ID: e24a9a2c6b41
Revises: c3a821e6d4f2
Create Date: 2026-08-05 22:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = "e24a9a2c6b41"
down_revision = "c3a821e6d4f2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "courses",
        sa.Column(
            "is_historical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
    )
    op.create_index(
        op.f("ix_courses_is_historical"),
        "courses",
        ["is_historical"],
        unique=False,
    )
    op.execute(
        sa.text(
            "UPDATE courses SET is_historical = 1 "
            "WHERE id IN (SELECT course_id FROM import_batches WHERE course_id IS NOT NULL)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.0', "
            "database_version = 3, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    op.drop_index(op.f("ix_courses_is_historical"), table_name="courses")
    op.drop_column("courses", "is_historical")
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.4.0', "
            "database_version = 2, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
