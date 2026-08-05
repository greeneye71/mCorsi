from pathlib import Path

from mcorsi.extensions import db
from mcorsi.models import User
from mcorsi.services.backup import create_backup, restore_backup, verify_backup


def test_backup_contains_database_and_storage(app, runner):
    storage = Path(app.config["PRIVATE_STORAGE_PATH"])
    (storage / "documenti").mkdir(parents=True)
    (storage / "documenti" / "esempio.txt").write_text("contenuto", encoding="utf-8")

    result = runner.invoke(args=["backup", "create"])
    assert result.exit_code == 0, result.output

    archives = list(Path(app.config["BACKUP_PATH"]).glob("*.mcbackup"))
    assert len(archives) == 1
    with app.app_context():
        manifest = verify_backup(archives[0])
    paths = {item["path"] for item in manifest["files"]}
    assert "database.sqlite3" in paths
    assert "storage/documenti/esempio.txt" in paths


def test_restore_replaces_database_and_storage_and_keeps_safety_backup(app):
    storage = Path(app.config["PRIVATE_STORAGE_PATH"])
    storage.mkdir(parents=True, exist_ok=True)
    marker = storage / "marker.txt"
    marker.write_text("originale", encoding="utf-8")
    with app.app_context():
        original = User(email="originale@example.it", profile_completed=True)
        db.session.add(original)
        db.session.commit()
        archive = create_backup()

        marker.write_text("modificato", encoding="utf-8")
        db.session.add(User(email="da-rimuovere@example.it", profile_completed=True))
        db.session.commit()
        restore_backup(archive)

        assert User.query.filter_by(email="originale@example.it").one()
        assert User.query.filter_by(email="da-rimuovere@example.it").first() is None
        assert marker.read_text(encoding="utf-8") == "originale"
        assert len(list(Path(app.config["BACKUP_PATH"]).glob("*.mcbackup"))) == 2


def test_backup_retention_keeps_latest_archives(app):
    with app.app_context():
        app.config["BACKUP_RETENTION_COUNT"] = 2
        create_backup()
        create_backup()
        create_backup()
        archives = list(Path(app.config["BACKUP_PATH"]).glob("*.mcbackup"))
        assert len(archives) == 2
