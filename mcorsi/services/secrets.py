from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class SecretDecryptionError(RuntimeError):
    pass


def _fernet() -> Fernet:
    material = current_app.config.get("ENCRYPTION_KEY", "")
    if not material:
        raise SecretDecryptionError("La chiave di cifratura non è configurata.")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Impossibile decifrare la password SMTP: controlla MCORSI_ENCRYPTION_KEY."
        ) from exc
