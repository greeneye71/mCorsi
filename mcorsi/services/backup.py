from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app

from .secrets import is_fernet_key


BACKUP_FORMAT_VERSION = 1
ENCRYPTED_BACKUP_MAGIC = b"MCBKUP02"
ENCRYPTION_CHUNK_SIZE = 4 * 1024 * 1024
_LENGTH = struct.Struct(">I")


class BackupEncryptionError(ValueError):
    pass


def _private_binary_writer(path: Path):
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    return os.fdopen(descriptor, "wb")


def _decode_backup_key(value: str, *, setting: str) -> bytes:
    if not is_fernet_key(value.strip()):
        raise BackupEncryptionError(f"{setting} non contiene una chiave valida.")
    return base64.urlsafe_b64decode(value.strip().encode("ascii"))


def _backup_keys() -> list[bytes]:
    primary = current_app.config.get("BACKUP_ENCRYPTION_KEY", "")
    if not primary:
        raise BackupEncryptionError(
            "Configura MCORSI_BACKUP_ENCRYPTION_KEY prima di creare o leggere backup."
        )
    keys = [_decode_backup_key(primary, setting="MCORSI_BACKUP_ENCRYPTION_KEY")]
    previous = current_app.config.get("BACKUP_DECRYPTION_KEYS", "")
    for value in (item.strip() for item in previous.split(",")):
        if value:
            keys.append(
                _decode_backup_key(value, setting="MCORSI_BACKUP_DECRYPTION_KEYS")
            )
    return keys


def _chunk_aad(nonce_prefix: bytes, counter: int, *, final: bool) -> bytes:
    return (
        ENCRYPTED_BACKUP_MAGIC
        + nonce_prefix
        + counter.to_bytes(4, "big")
        + (b"\x01" if final else b"\x00")
    )


def _encrypt_file(source_path: Path, destination_path: Path) -> None:
    cipher = AESGCM(_backup_keys()[0])
    nonce_prefix = os.urandom(8)
    counter = 0
    with source_path.open("rb") as source, _private_binary_writer(
        destination_path
    ) as destination:
        destination.write(ENCRYPTED_BACKUP_MAGIC)
        destination.write(nonce_prefix)
        while chunk := source.read(ENCRYPTION_CHUNK_SIZE):
            if counter >= 2**32 - 1:
                raise BackupEncryptionError("Il backup supera la dimensione supportata.")
            nonce = nonce_prefix + counter.to_bytes(4, "big")
            encrypted = cipher.encrypt(
                nonce, chunk, _chunk_aad(nonce_prefix, counter, final=False)
            )
            destination.write(_LENGTH.pack(len(encrypted)))
            destination.write(encrypted)
            counter += 1
        nonce = nonce_prefix + counter.to_bytes(4, "big")
        final = cipher.encrypt(
            nonce, b"", _chunk_aad(nonce_prefix, counter, final=True)
        )
        destination.write(_LENGTH.pack(len(final)))
        destination.write(final)


def _read_exact(source, size: int) -> bytes:
    value = source.read(size)
    if len(value) != size:
        raise BackupEncryptionError("Il backup cifrato è troncato.")
    return value


def _decrypt_file(source_path: Path, destination_path: Path) -> None:
    keys = _backup_keys()
    selected_cipher: AESGCM | None = None
    with source_path.open("rb") as source, _private_binary_writer(
        destination_path
    ) as destination:
        if _read_exact(source, len(ENCRYPTED_BACKUP_MAGIC)) != ENCRYPTED_BACKUP_MAGIC:
            raise BackupEncryptionError("Formato del backup cifrato non riconosciuto.")
        nonce_prefix = _read_exact(source, 8)
        counter = 0
        while True:
            encrypted_size = _LENGTH.unpack(_read_exact(source, _LENGTH.size))[0]
            if encrypted_size < 16 or encrypted_size > ENCRYPTION_CHUNK_SIZE + 16:
                raise BackupEncryptionError("Dimensione di blocco del backup non valida.")
            encrypted = _read_exact(source, encrypted_size)
            final = encrypted_size == 16
            nonce = nonce_prefix + counter.to_bytes(4, "big")
            aad = _chunk_aad(nonce_prefix, counter, final=final)
            if selected_cipher is None:
                for key in keys:
                    candidate = AESGCM(key)
                    try:
                        plain = candidate.decrypt(nonce, encrypted, aad)
                    except InvalidTag:
                        continue
                    selected_cipher = candidate
                    break
                else:
                    raise BackupEncryptionError(
                        "Chiave errata o backup cifrato danneggiato."
                    )
            else:
                try:
                    plain = selected_cipher.decrypt(nonce, encrypted, aad)
                except InvalidTag as exc:
                    raise BackupEncryptionError(
                        "Il backup cifrato è stato alterato o danneggiato."
                    ) from exc
            if final:
                if plain or source.read(1):
                    raise BackupEncryptionError("Terminazione del backup non valida.")
                return
            destination.write(plain)
            counter += 1
            if counter >= 2**32:
                raise BackupEncryptionError("Il backup supera la dimensione supportata.")


@contextmanager
def _readable_archive(
    archive_path: Path, *, allow_legacy_unencrypted: bool = False
):
    with archive_path.open("rb") as source:
        signature = source.read(len(ENCRYPTED_BACKUP_MAGIC))
    if signature == ENCRYPTED_BACKUP_MAGIC:
        staging_root = Path(current_app.instance_path) / "backup-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        plain_path = staging_root / f"{uuid.uuid4().hex}.zip"
        try:
            _decrypt_file(archive_path, plain_path)
            yield plain_path
        finally:
            plain_path.unlink(missing_ok=True)
        return
    if signature.startswith(b"PK"):
        if not allow_legacy_unencrypted:
            raise BackupEncryptionError(
                "Backup legacy non cifrato: ripeti con l'opzione esplicita di compatibilità."
            )
        yield archive_path
        return
    raise BackupEncryptionError("Formato del backup non riconosciuto.")


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

        plain_archive = temp_dir / "archive.zip"
        with _private_binary_writer(plain_archive):
            pass
        with zipfile.ZipFile(plain_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            archive.write(database_copy, "database.sqlite3")
            if storage_copy.exists():
                for path in sorted(p for p in storage_copy.rglob("*") if p.is_file()):
                    archive.write(path, path.relative_to(temp_dir).as_posix())
        _verify_zip(plain_archive)
        _encrypt_file(plain_archive, partial_path)
        verify_backup(partial_path)
        partial_path.replace(archive_path)
        prune_backups(backup_dir)
    finally:
        partial_path.unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
    return archive_path


def _verify_zip(path: Path) -> dict:
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


def verify_backup(
    archive_path: str | Path, *, allow_legacy_unencrypted: bool = False
) -> dict:
    path = Path(archive_path).resolve()
    with _readable_archive(
        path, allow_legacy_unencrypted=allow_legacy_unencrypted
    ) as readable_path:
        return _verify_zip(readable_path)


def encrypt_legacy_backup(
    archive_path: str | Path, destination: str | Path | None = None
) -> Path:
    source_path = Path(archive_path).resolve()
    with source_path.open("rb") as source:
        signature = source.read(len(ENCRYPTED_BACKUP_MAGIC))
    if signature == ENCRYPTED_BACKUP_MAGIC:
        raise BackupEncryptionError("Il backup è già cifrato.")
    verify_backup(source_path, allow_legacy_unencrypted=True)

    destination_path = (
        Path(destination).resolve()
        if destination
        else source_path.with_name(f"{source_path.stem}-encrypted.mcbackup")
    )
    if destination_path == source_path:
        raise BackupEncryptionError("La conversione non può sovrascrivere l'originale.")
    if destination_path.exists():
        raise FileExistsError(f"Il file di destinazione esiste già: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = destination_path.with_suffix(destination_path.suffix + ".partial")
    if partial_path.exists():
        raise FileExistsError(f"Il file temporaneo esiste già: {partial_path}")
    try:
        _encrypt_file(source_path, partial_path)
        verify_backup(partial_path)
        partial_path.replace(destination_path)
    finally:
        partial_path.unlink(missing_ok=True)
    return destination_path


def restore_backup(
    archive_path: str | Path,
    *,
    safety_backup: bool = True,
    allow_legacy_unencrypted: bool = False,
) -> dict:
    """Ripristina database e storage; deve essere chiamato con il server web fermo."""
    archive_path = Path(archive_path).resolve()
    source_db = _sqlite_path()
    storage_path = Path(current_app.config["PRIVATE_STORAGE_PATH"]).resolve()
    with _readable_archive(
        archive_path, allow_legacy_unencrypted=allow_legacy_unencrypted
    ) as readable_path:
        manifest = _verify_zip(readable_path)
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
            with zipfile.ZipFile(readable_path, "r") as archive:
                database_new.write_bytes(archive.read("database.sqlite3"))
                for item in manifest.get("files", []):
                    relative = Path(item["path"])
                    if relative.as_posix() == "database.sqlite3":
                        continue
                    parts = relative.parts
                    if (
                        not parts
                        or parts[0] != "storage"
                        or relative.is_absolute()
                        or ".." in parts
                    ):
                        raise ValueError(f"Percorso non valido nel backup: {item['path']}")
                    destination = (storage_new / Path(*parts[1:])).resolve()
                    if storage_new.resolve() not in destination.parents:
                        raise ValueError(f"Percorso non valido nel backup: {item['path']}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(item["path"]))
            with closing(sqlite3.connect(database_new)) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise ValueError(
                        "Il database del backup non supera il controllo di integrità."
                    )

            from ..extensions import db

            db.session.remove()
            db.engine.dispose()
            if storage_old.exists():
                raise RuntimeError("Esiste già una directory temporanea di ripristino.")
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
