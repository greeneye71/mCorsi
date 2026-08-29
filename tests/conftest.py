from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from mcorsi import create_app
from mcorsi.cli import ensure_roles
from mcorsi.extensions import db


@pytest.fixture()
def app():
    test_root = (Path.cwd() / "instance" / "test-data" / uuid4().hex).resolve()
    test_root.mkdir(parents=True)
    database_path = test_root / "test.sqlite3"
    storage_path = test_root / "storage"
    backup_path = test_root / "backups"
    application = create_app(
        "testing",
        {
            "SECRET_KEY": "testing-secret",
            "ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "BACKUP_ENCRYPTION_KEY": "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "PRIVATE_STORAGE_PATH": str(storage_path),
            "BACKUP_PATH": str(backup_path),
            "MAIL_OUTBOX": [],
        },
    )
    with application.app_context():
        db.create_all()
        ensure_roles()
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()
