from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app


BACKUP_FORMAT_VERSION = 1


def prune_backups(folder: str | Path | None = None, *, keep: int | None = None) -> list[Path]:
    backup_dir = Path(folder or current_app.config["BACKUP_PATH"]).resolve()
    retention = current_app.config["BACKUP_RETENTION_COUNT"] if keep is None else keep
    if retention < 1 or not backup_dir.exists():
        return []
    archives = sorted(backup_dir.glob("*.mcbackup"), key=lambda item: item.name, reverse=True)
    removed = []
    for archive in archives[retention:]:
        archive.unlink()
        removed.append(archive)
    return removed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_path() -> Path:
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    prefix = "sqlite:///"
    if not uri.startswith(prefix) or uri.endswith(":memory:"):
        raise RuntimeError("Il backup integrato richiede un database SQLite su file.")
    return Path(uri.removeprefix(prefix)).resolve()


def create_backup(destination: str | Path | None = None) -> Path:
    source_db = _sqlite_path()
    if not source_db.exists():
        raise FileNotFoundError("Il database non esiste ancora.")

    backup_dir = Path(destination or current_app.config["BACKUP_PATH"]).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = backup_dir / f"mcorsi-{timestamp}.mcbackup"
    partial_path = archive_path.with_suffix(".mcbackup.partial")
    storage_path = Path(current_app.config["PRIVATE_STORAGE_PATH"]).resolve()

    staging_root = Path(current_app.instance_path) / "backup-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    temp_dir = staging_root / uuid.uuid4().hex
    temp_dir.mkdir()
    try:
        database_copy = temp_dir / "database.sqlite3"
        with closing(sqlite3.connect(source_db)) as source, closing(sqlite3.connect(database_copy)) as target:
            source.backup(target)

        files: list[dict[str, str | int]] = []
        files.append(
            {
                "path": "database.sqlite3",
                "sha256": _sha256_file(database_copy),
                "size": database_copy.stat().st_size,
            }
        )

        storage_copy = temp_dir / "storage"
        if storage_path.exists():
            shutil.copytree(storage_path, storage_copy, ignore=shutil.ignore_patterns(".work"))
            for path in sorted(p for p in storage_copy.rglob("*") if p.is_file()):
                files.append(
                    {
                        "path": path.relative_to(temp_dir).as_posix(),
                        "sha256": _sha256_file(path),
                        "size": path.stat().st_size,
                    }
                )

        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "application": "mCorsi",
            "files": files,
        }
        manifest_path = temp_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        with zipfile.ZipFile(partial_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            archive.write(database_copy, "database.sqlite3")
            if storage_copy.exists():
                for path in sorted(p for p in storage_copy.rglob("*") if p.is_file()):
                    archive.write(path, path.relative_to(temp_dir).as_posix())
        verify_backup(partial_path)
        partial_path.replace(archive_path)
        prune_backups(backup_dir)
    finally:
        partial_path.unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
    return archive_path


def verify_backup(archive_path: str | Path) -> dict:
    path = Path(archive_path).resolve()
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise ValueError("L'archivio ZIP contiene dati danneggiati.")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except KeyError as exc:
            raise ValueError("Il backup non contiene il manifest.") from exc
        if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
            raise ValueError("Versione del formato di backup non supportata.")
        entries = set(archive.namelist())
        for item in manifest.get("files", []):
            item_path = item["path"]
            if item_path not in entries:
                raise ValueError(f"File mancante nel backup: {item_path}")
            digest = hashlib.sha256(archive.read(item_path)).hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"Checksum non valido: {item_path}")
    return manifest


def restore_backup(archive_path: str | Path, *, safety_backup: bool = True) -> dict:
    """Ripristina database e storage; deve essere chiamato con il server web fermo."""
    archive_path = Path(archive_path).resolve()
    manifest = verify_backup(archive_path)
    source_db = _sqlite_path()
    storage_path = Path(current_app.config["PRIVATE_STORAGE_PATH"]).resolve()
    if safety_backup and source_db.exists():
        create_backup()

    operation_id = uuid.uuid4().hex
    database_new = source_db.parent / f".{source_db.name}.restore-{operation_id}"
    storage_new = storage_path.parent / f".{storage_path.name}.restore-{operation_id}"
    storage_old = storage_path.parent / f".{storage_path.name}.before-restore-{operation_id}"
    source_db.parent.mkdir(parents=True, exist_ok=True)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_new.mkdir()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            database_new.write_bytes(archive.read("database.sqlite3"))
            for item in manifest.get("files", []):
                relative = Path(item["path"])
                if relative.as_posix() == "database.sqlite3":
                    continue
                parts = relative.parts
                if not parts or parts[0] != "storage" or relative.is_absolute() or ".." in parts:
                    raise ValueError(f"Percorso non valido nel backup: {item['path']}")
                destination = (storage_new / Path(*parts[1:])).resolve()
                if storage_new.resolve() not in destination.parents:
                    raise ValueError(f"Percorso non valido nel backup: {item['path']}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(item["path"]))
        with closing(sqlite3.connect(database_new)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("Il database del backup non supera il controllo di integrità.")

        from ..extensions import db

        db.session.remove()
        db.engine.dispose()
        if storage_path.exists():
            storage_path.replace(storage_old)
        storage_new.replace(storage_path)
        try:
            database_new.replace(source_db)
            source_db.with_name(source_db.name + "-wal").unlink(missing_ok=True)
            source_db.with_name(source_db.name + "-shm").unlink(missing_ok=True)
        except Exception:
            if storage_path.exists():
                shutil.rmtree(storage_path, ignore_errors=True)
            if storage_old.exists():
                storage_old.replace(storage_path)
            raise
        if storage_old.exists():
            shutil.rmtree(storage_old, ignore_errors=True)
    finally:
        database_new.unlink(missing_ok=True)
        if storage_new.exists():
            shutil.rmtree(storage_new, ignore_errors=True)
    return manifest
