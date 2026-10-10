"""revoca sessioni e coda notifiche

Revision ID: f3b9c1d7e5a2
Revises: d51f2a8c90be
Create Date: 2026-10-10 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "f3b9c1d7e5a2"
down_revision = "d51f2a8c90be"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("session_token", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE users SET session_token = lower(hex(randomblob(16)))"))
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("session_token", existing_type=sa.String(length=64), nullable=False)
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.6.0', "
            "database_version = 7, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("session_token")
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.16', "
            "database_version = 6, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
