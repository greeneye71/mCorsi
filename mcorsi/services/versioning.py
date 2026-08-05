from __future__ import annotations

from sqlalchemy import text

from ..extensions import db
from ..models import SystemVersion
from ..version import APP_VERSION, DATABASE_VERSION


def ensure_system_version() -> SystemVersion:
    """Inizializza i metadati nei database creati senza Alembic, come nei test."""
    stored = db.session.get(SystemVersion, 1)
    if stored is None:
        stored = SystemVersion(
            id=1,
            application_version=APP_VERSION,
            database_version=DATABASE_VERSION,
        )
        db.session.add(stored)
        db.session.flush()
    elif stored.database_version == DATABASE_VERSION:
        stored.application_version = APP_VERSION
    return stored


def alembic_revision() -> str | None:
    try:
        return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        db.session.rollback()
        return None


def version_information() -> dict[str, str | int | bool | None]:
    stored = db.session.get(SystemVersion, 1)
    return {
        "application_version": APP_VERSION,
        "required_database_version": DATABASE_VERSION,
        "database_version": stored.database_version if stored else None,
        "database_application_version": stored.application_version if stored else None,
        "alembic_revision": alembic_revision(),
        "compatible": bool(stored and stored.database_version == DATABASE_VERSION),
    }
