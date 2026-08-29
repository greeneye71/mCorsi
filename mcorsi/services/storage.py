from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from flask import current_app
from PIL import Image
from pypdf import PdfReader
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

CANONICAL_MIME_TYPES = {
    ".csv": "text/csv",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_STRUCTURE_ENTRY_BYTES = 20 * 1024 * 1024


def _validate_text(path: Path) -> None:
    content = path.read_bytes()
    if b"\x00" in content:
        raise StorageError("Il file di testo contiene dati binari.")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StorageError("Il file di testo deve usare la codifica UTF-8.") from exc


def _validate_image(path: Path, expected_format: str) -> None:
    try:
        with Image.open(path) as image:
            if image.format != expected_format:
                raise StorageError(
                    "Il contenuto dell'immagine non corrisponde all'estensione."
                )
            image.verify()
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError("Il file non contiene un'immagine valida.") from exc


def _validate_pdf(path: Path) -> None:
    try:
        with path.open("rb") as source:
            if not source.read(5).startswith(b"%PDF-"):
                raise ValueError
        reader = PdfReader(str(path))
        if not reader.pages:
            raise ValueError
    except Exception as exc:
        raise StorageError("Il file non contiene un PDF valido.") from exc


def _validate_zip_container(path: Path, suffix: str) -> None:
    required_entry = {
        ".docx": "word/document.xml",
        ".xlsx": "xl/workbook.xml",
        ".pptx": "ppt/presentation.xml",
    }.get(suffix)
    open_document_mime = {
        ".odt": b"application/vnd.oasis.opendocument.text",
        ".ods": b"application/vnd.oasis.opendocument.spreadsheet",
    }.get(suffix)
    expected_root = {
        ".docx": "document",
        ".xlsx": "workbook",
        ".pptx": "presentation",
        ".odt": "document-content",
        ".ods": "document-content",
    }[suffix]
    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
                raise StorageError("Il contenitore del documento ha troppi elementi.")
            if any(item.flag_bits & 0x1 for item in entries):
                raise StorageError("I documenti ZIP cifrati non sono consentiti.")
            if sum(item.file_size for item in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise StorageError("Il contenuto espanso del documento è troppo grande.")
            names = {item.filename for item in entries}
            if len(names) != len(entries):
                raise StorageError("Il documento contiene elementi duplicati.")
            for name in names:
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                    raise StorageError("Il documento contiene percorsi non validi.")
            if any(name.casefold().endswith("vbaproject.bin") for name in names):
                raise StorageError("I documenti con macro non sono consentiti.")
            if required_entry:
                if required_entry not in names or "[Content_Types].xml" not in names:
                    raise StorageError(
                        "Il contenuto del documento non corrisponde all'estensione."
                    )
                structure_entry = required_entry
            elif open_document_mime:
                if (
                    "mimetype" not in names
                    or "content.xml" not in names
                    or archive.read("mimetype") != open_document_mime
                ):
                    raise StorageError(
                        "Il contenuto OpenDocument non corrisponde all'estensione."
                    )
                structure_entry = "content.xml"
            structure_info = archive.getinfo(structure_entry)
            if structure_info.file_size > MAX_STRUCTURE_ENTRY_BYTES:
                raise StorageError("La struttura XML del documento è troppo grande.")
            root = ElementTree.fromstring(archive.read(structure_entry))
            if root.tag.rsplit("}", 1)[-1] != expected_root:
                raise StorageError(
                    "La struttura interna del documento non corrisponde all'estensione."
                )
    except StorageError:
        raise
    except (
        DefusedXmlException,
        ElementTree.ParseError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as exc:
        raise StorageError("Il file non contiene un documento ZIP valido.") from exc


def canonical_mime_type(filename: str) -> str:
    suffix = Path(filename).suffix.casefold()
    return CANONICAL_MIME_TYPES.get(suffix, "application/octet-stream")


def detect_mime_type(path: Path, suffix: str) -> str:
    mime_type = canonical_mime_type(f"file{suffix}")
    if mime_type == "application/octet-stream":
        raise StorageError("Formato del file non consentito.")
    if suffix in {".docx", ".xlsx", ".pptx", ".odt", ".ods"}:
        _validate_zip_container(path, suffix)
    elif suffix in {".jpg", ".jpeg"}:
        _validate_image(path, "JPEG")
    elif suffix == ".png":
        _validate_image(path, "PNG")
    elif suffix == ".pdf":
        _validate_pdf(path)
    elif suffix in {".txt", ".csv"}:
        _validate_text(path)
    return mime_type


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
        if size == 0:
            raise StorageError("Il file è vuoto.")
        mime_type = detect_mime_type(destination, suffix)
        normalized_allowed_mime_types = {
            item.casefold() for item in allowed_mime_types or set()
        }
        if (
            allowed_mime_types is not None
            and mime_type not in normalized_allowed_mime_types
        ):
            raise StorageError("Tipo del file non consentito.")
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise StorageError("Impossibile archiviare il file.") from exc
    except StorageError:
        destination.unlink(missing_ok=True)
        raise

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
