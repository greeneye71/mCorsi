from __future__ import annotations

import base64
import hashlib
import secrets as python_secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from flask import current_app


class SecretDecryptionError(RuntimeError):
    pass


def generate_secret_values() -> dict[str, str]:
    return {
        "MCORSI_SECRET_KEY": python_secrets.token_urlsafe(48),
        "MCORSI_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "MCORSI_OTP_PEPPER": python_secrets.token_urlsafe(48),
        "MCORSI_MCP_TOKEN_PEPPER": python_secrets.token_urlsafe(48),
    }


def is_fernet_key(value: str) -> bool:
    try:
        Fernet((value or "").encode("ascii"))
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    return True


def _load_fernet(value: str, *, setting: str) -> Fernet:
    try:
        return Fernet(value.strip().encode("ascii"))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SecretDecryptionError(
            f"{setting} non contiene una chiave Fernet valida."
        ) from exc


def _legacy_fernet(material: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def _fernet() -> MultiFernet:
    primary = current_app.config.get("ENCRYPTION_KEY", "").strip()
    if not primary:
        raise SecretDecryptionError("La chiave di cifratura non è configurata.")
    fernets = [_load_fernet(primary, setting="MCORSI_ENCRYPTION_KEY")]
    previous_keys = current_app.config.get("ENCRYPTION_PREVIOUS_KEYS", "")
    for previous in (item.strip() for item in previous_keys.split(",")):
        if previous:
            fernets.append(
                _load_fernet(previous, setting="MCORSI_ENCRYPTION_PREVIOUS_KEYS")
            )
    legacy_material = current_app.config.get("LEGACY_ENCRYPTION_KEY", "")
    if legacy_material:
        fernets.append(_legacy_fernet(legacy_material))
    return MultiFernet(fernets)


def has_decryption_fallbacks() -> bool:
    return bool(
        current_app.config.get("ENCRYPTION_PREVIOUS_KEYS", "").strip()
        or current_app.config.get("LEGACY_ENCRYPTION_KEY", "")
    )


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError) as exc:
        raise SecretDecryptionError(
            "Impossibile decifrare la password SMTP: controlla MCORSI_ENCRYPTION_KEY."
        ) from exc


def rotate_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().rotate(token.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeEncodeError) as exc:
        raise SecretDecryptionError(
            "Impossibile ruotare il segreto: configura la chiave precedente o legacy."
        ) from exc
