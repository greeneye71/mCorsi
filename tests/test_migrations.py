"""Le migrazioni SQLite che ricreano tabelle non devono perdere dati figli."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from flask_migrate import upgrade

from mcorsi import create_app

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _app(database_path: Path):
    return create_app(
        "testing",
        {
            "SECRET_KEY": "testing-secret",
            "ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "PRIVATE_STORAGE_PATH": str(database_path.parent / "storage"),
            "BACKUP_PATH": str(database_path.parent / "backups"),
            "MAIL_OUTBOX": [],
        },
    )


def _database_path() -> Path:
    root = (Path.cwd() / "instance" / "test-data" / uuid4().hex).resolve()
    root.mkdir(parents=True)
    return root / "migrazioni.sqlite3"


def _migrate(app, revision: str) -> None:
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR, revision=revision)


def _insert(connection: sqlite3.Connection, table: str, **values) -> None:
    row = {}
    for _cid, name, kind, notnull, default, pk in connection.execute(
        f"PRAGMA table_info({table})"
    ):
        kind = kind.upper()
        if pk and kind.startswith("INT"):
            continue
        if notnull and default is None:
            if "BOOL" in kind or "INT" in kind:
                row[name] = 0
            elif "DATETIME" in kind:
                row[name] = "2026-01-01 00:00:00"
            elif "DATE" in kind:
                row[name] = "2026-01-01"
            elif "TIME" in kind:
                row[name] = "09:00:00"
            else:
                row[name] = "x"
    row.update(values)
    placeholders = ",".join("?" * len(row))
    connection.execute(
        f"INSERT INTO {table} ({','.join(row)}) VALUES ({placeholders})", list(row.values())
    )


def _counts(database_path: Path, tables: list[str]) -> list[int]:
    connection = sqlite3.connect(database_path)
    try:
        return [connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]
    finally:
        connection.close()


def test_table_rebuild_keeps_cascading_children():
    database_path = _database_path()
    app = _app(database_path)
    _migrate(app, "c74d1f83a602")
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys=ON")
    _insert(connection, "users", id="u1", email="admin@example.it")
    _insert(connection, "users", id="u2", email="persona@example.it")
    role_id = connection.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
    if role_id is None:
        _insert(connection, "roles", name="admin")
        role_id = connection.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
    _insert(connection, "user_roles", user_id="u1", role_id=role_id[0])
    _insert(
        connection,
        "courses",
        id="c1",
        creator_user_id="u1",
        referent_user_id="u1",
        status="open",
        delivery_mode="online",
    )
    _insert(connection, "course_sessions", id="s1", course_id="c1")
    _insert(
        connection,
        "enrollments",
        id="e1",
        course_id="c1",
        participant_user_id="u2",
        attendance_status="attended",
    )
    connection.commit()
    connection.close()

    tables = ["users", "user_roles", "courses", "course_sessions", "enrollments"]
    _migrate(app, "head")

    assert _counts(database_path, tables) == [2, 1, 1, 1, 1]
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        tokens = connection.execute("SELECT session_token FROM users").fetchall()
        assert all(token for (token,) in tokens)
    finally:
        connection.close()


def test_session_token_migration_resumes_after_partial_failure():
    database_path = _database_path()
    app = _app(database_path)
    _migrate(app, "d51f2a8c90be")
    connection = sqlite3.connect(database_path)
    _insert(connection, "users", id="u1", email="admin@example.it")
    # Stato lasciato da un tentativo interrotto: colonna aggiunta, revisione
    # non registrata, tabella temporanea di batch rimasta.
    connection.execute("ALTER TABLE users ADD COLUMN session_token VARCHAR(64)")
    connection.execute("CREATE TABLE _alembic_tmp_users (id VARCHAR(36))")
    connection.commit()
    connection.close()

    _migrate(app, "head")

    connection = sqlite3.connect(database_path)
    try:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert "_alembic_tmp_users" not in names
        (token,) = connection.execute("SELECT session_token FROM users").fetchone()
        assert token
    finally:
        connection.close()
