"""verifica associazioni aziendali

Revision ID: a91c8e7d42f6
Revises: e24a9a2c6b41
Create Date: 2026-08-29 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "a91c8e7d42f6"
down_revision = "e24a9a2c6b41"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=20),
                nullable=False,
                server_default="verified",
            )
        )
        batch_op.add_column(
            sa.Column("requested_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            op.f("ix_employments_verification_status"),
            ["verification_status"],
            unique=False,
        )
        batch_op.create_foreign_key(
            op.f("fk_employments_requested_by_user_id_users"),
            "users",
            ["requested_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_employments_reviewed_by_user_id_users"),
            "users",
            ["reviewed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.3', "
            "database_version = 4, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )


def downgrade():
    with op.batch_alter_table("employments") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_employments_reviewed_by_user_id_users"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            op.f("fk_employments_requested_by_user_id_users"), type_="foreignkey"
        )
        batch_op.drop_index(op.f("ix_employments_verification_status"))
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by_user_id")
        batch_op.drop_column("requested_by_user_id")
        batch_op.drop_column("verification_status")
    op.execute(
        sa.text(
            "UPDATE system_version SET application_version = '0.5.2', "
            "database_version = 3, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
