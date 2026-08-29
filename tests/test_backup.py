import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import mcorsi.services.backup as backup_service
from mcorsi.extensions import db
from mcorsi.models import User
from mcorsi.services.backup import (
    BackupEncryptionError,
    ENCRYPTED_BACKUP_MAGIC,
    create_backup,
    encrypt_legacy_backup,
    restore_backup,
    verify_backup,
)


def test_backup_contains_database_and_storage(app, runner):
    storage = Path(app.config["PRIVATE_STORAGE_PATH"])
    (storage / "documenti").mkdir(parents=True)
    (storage / "documenti" / "esempio.txt").write_text("contenuto", encoding="utf-8")

    result = runner.invoke(args=["backup", "create"])
    assert result.exit_code == 0, result.output

    archives = list(Path(app.config["BACKUP_PATH"]).glob("*.mcbackup"))
    assert len(archives) == 1
    archive_bytes = archives[0].read_bytes()
    assert archive_bytes.startswith(ENCRYPTED_BACKUP_MAGIC)
    assert not archive_bytes.startswith(b"PK")
    assert b"SQLite format 3" not in archive_bytes
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


def test_backup_authentication_rejects_tampering_and_wrong_key(app):
    with app.app_context():
        original_key = app.config["BACKUP_ENCRYPTION_KEY"]
        archive = create_backup()
        app.config["BACKUP_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
        with pytest.raises(BackupEncryptionError, match="Chiave errata"):
            verify_backup(archive)

        app.config["BACKUP_DECRYPTION_KEYS"] = original_key
        assert verify_backup(archive)["application"] == "mCorsi"
        app.config["BACKUP_ENCRYPTION_KEY"] = original_key
        app.config["BACKUP_DECRYPTION_KEYS"] = ""

        damaged = archive.with_name("danneggiato.mcbackup")
        content = bytearray(archive.read_bytes())
        content[-8] ^= 0x01
        damaged.write_bytes(content)
        with pytest.raises(BackupEncryptionError, match="alterato|danneggiato"):
            verify_backup(damaged)


def test_encrypted_backup_supports_multiple_authenticated_chunks(app, monkeypatch):
    monkeypatch.setattr(backup_service, "ENCRYPTION_CHUNK_SIZE", 64)
    with app.app_context():
        archive = create_backup()
        assert verify_backup(archive)["application"] == "mCorsi"


def test_legacy_backup_requires_opt_in_and_can_be_converted(app):
    backup_dir = Path(app.config["BACKUP_PATH"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    legacy = backup_dir / "legacy.mcbackup"
    database_content = b"database legacy di prova"
    manifest = {
        "format_version": 1,
        "created_at": "2026-08-29T12:00:00+00:00",
        "application": "mCorsi",
        "files": [
            {
                "path": "database.sqlite3",
                "sha256": hashlib.sha256(database_content).hexdigest(),
                "size": len(database_content),
            }
        ],
    }
    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("database.sqlite3", database_content)

    with app.app_context():
        with pytest.raises(BackupEncryptionError, match="legacy non cifrato"):
            verify_backup(legacy)
        assert verify_backup(legacy, allow_legacy_unencrypted=True) == manifest
        converted = encrypt_legacy_backup(legacy)
        assert converted.read_bytes().startswith(ENCRYPTED_BACKUP_MAGIC)
        assert verify_backup(converted) == manifest
        assert legacy.exists()
