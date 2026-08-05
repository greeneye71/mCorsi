from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import StoredFile, User


class StorageError(ValueError):
    pass


SAFE_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".docx",
    ".jpeg",
    ".jpg",
    ".ods",
    ".odt",
    ".pdf",
    ".png",
    ".pptx",
    ".txt",
    ".xlsx",
}


def storage_root() -> Path:
    return Path(current_app.config["PRIVATE_STORAGE_PATH"]).resolve()


def path_for(stored_file: StoredFile) -> Path:
    root = storage_root()
    path = (root / stored_file.storage_key).resolve()
    if root not in path.parents:
        raise StorageError("Percorso di archiviazione non valido.")
    return path


def save_upload(
    upload: FileStorage,
    *,
    actor: User,
    category: str,
    allowed_extensions: set[str] | None = None,
    allowed_mime_types: set[str] | None = None,
) -> StoredFile:
    original_name = secure_filename(upload.filename or "")
    if not original_name:
        raise StorageError("Il file non ha un nome valido.")
    suffix = Path(original_name).suffix.casefold()
    if allowed_extensions is None:
        allowed_extensions = SAFE_DOCUMENT_EXTENSIONS
    if allowed_extensions is not None and suffix not in allowed_extensions:
        raise StorageError("Formato del file non consentito.")
    mime_type = (upload.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").casefold()
    if allowed_mime_types is not None and mime_type not in allowed_mime_types:
        raise StorageError("Tipo del file non consentito.")

    now = datetime.now(timezone.utc)
    storage_key = f"{category}/{now:%Y/%m}/{uuid4().hex}{suffix}"
    destination = (storage_root() / storage_key).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    upload.stream.seek(0)
    try:
        with destination.open("wb") as output:
            while chunk := upload.stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise StorageError("Impossibile archiviare il file.") from exc
    if size == 0:
        destination.unlink(missing_ok=True)
        raise StorageError("Il file è vuoto.")

    record = StoredFile(
        storage_key=storage_key,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size,
        sha256=digest.hexdigest(),
        uploaded_by_user_id=actor.id,
    )
    db.session.add(record)
    db.session.flush()
    return record


def save_bytes(
    content: bytes,
    *,
    filename: str,
    mime_type: str,
    actor: User,
    category: str,
) -> StoredFile:
    from io import BytesIO

    upload = FileStorage(stream=BytesIO(content), filename=filename, content_type=mime_type)
    return save_upload(upload, actor=actor, category=category)
