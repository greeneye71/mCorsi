"""scadenza e unicita tentativi

Revision ID: c74d1f83a602
Revises: a91c8e7d42f6
Create Date: 2026-08-29 16:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "c74d1f83a602"
down_revision = "a91c8e7d42f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("questionnaire_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("open_slot", sa.Boolean(), nullable=True))

    # I vecchi tentativi aperti non avevano una scadenza affidabile: vengono
    # chiusi durante la migrazione, ma continuano a consumare il loro slot.
    op.execute(
        sa.text(
            "UPDATE questionnaire_attempts "
            "SET expires_at = CURRENT_TIMESTAMP, expired_at = CURRENT_TIMESTAMP "
            "WHERE submitted_at IS NULL"
        )
    )

    with op.batch_alter_table("questionnaire_attempts") as batch_op:
        batch_op.create_index(
            op.f("ix_questionnaire_attempts_expires_at"),
            ["expires_at"],
            unique=False,
        )
        batch_op.create_index(
            op.f("ix_questionnaire_attempts_expired_at"),
            ["expired_at"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_questionnaire_open_attempt",
            ["questionnaire_id", "participant_user_id", "open_slot"],
        )
        batch_op.create_check_constraint(
            "ck_questionnaire_attempt_state",
            "(open_slot IS TRUE AND submitted_at IS NULL AND expired_at IS NULL "
            "AND expires_at IS NOT NULL) OR "
            "(open_slot IS NULL AND submitted_at IS NOT NULL AND expired_at IS NULL) OR "
            "(open_slot IS NULL AND submitted_at IS NULL AND expired_at IS NOT NULL)",
        )

    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.7', "
            "database_version = 5, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    with op.batch_alter_table("questionnaire_attempts") as batch_op:
        batch_op.drop_constraint("ck_questionnaire_attempt_state", type_="check")
        batch_op.drop_constraint("uq_questionnaire_open_attempt", type_="unique")
        batch_op.drop_index(op.f("ix_questionnaire_attempts_expired_at"))
        batch_op.drop_index(op.f("ix_questionnaire_attempts_expires_at"))
        batch_op.drop_column("open_slot")
        batch_op.drop_column("expired_at")
        batch_op.drop_column("expires_at")

    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.6', "
            "database_version = 4, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
