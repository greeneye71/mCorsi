"""riferimenti legislativi e argomenti del corso

Revision ID: c3a821e6d4f2
Revises: 707b9cfc0a06
Create Date: 2026-08-05 21:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = "c3a821e6d4f2"
down_revision = "707b9cfc0a06"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("courses") as batch_op:
        batch_op.add_column(
            sa.Column("legal_references", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("topics", sa.Text(), nullable=False, server_default=""))
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.4.0', "
            "database_version = 2, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    with op.batch_alter_table("courses") as batch_op:
        batch_op.drop_column("topics")
        batch_op.drop_column("legal_references")
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.3.2', "
            "database_version = 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
