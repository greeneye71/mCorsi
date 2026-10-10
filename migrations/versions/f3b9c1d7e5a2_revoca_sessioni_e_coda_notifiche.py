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
    # Idempotente: su SQLite il DDL non è transazionale, quindi un tentativo
    # precedente interrotto può aver già aggiunto la colonna o lasciato la
    # tabella temporanea di batch_alter_table.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "_alembic_tmp_users" in tables:
        if "users" not in tables:
            raise RuntimeError(
                "Migrazione interrotta: tabella users assente e _alembic_tmp_users "
                "presente. Ripristinare un backup prima di riprovare."
            )
        op.drop_table("_alembic_tmp_users")

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "session_token" not in columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("session_token", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET session_token = lower(hex(randomblob(16))) "
            "WHERE session_token IS NULL OR session_token = ''"
        )
    )
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
