from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from mcorsi import create_app
from mcorsi.extensions import db
from mcorsi.models import Role, SmtpConfiguration, User
from mcorsi.services.secrets import SecretDecryptionError, decrypt_secret, rotate_secret


PRIMARY_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
PREVIOUS_KEY = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
LEGACY_MATERIAL = "vecchia-passphrase-di-cifratura"


def _legacy_token(value: str) -> str:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(LEGACY_MATERIAL.encode("utf-8")).digest()
    )
    return Fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def test_previous_fernet_key_can_only_decrypt_and_rotate(app):
    old_token = Fernet(PREVIOUS_KEY.encode("ascii")).encrypt(b"segreto")
    with app.app_context():
        app.config.update(
            ENCRYPTION_KEY=PRIMARY_KEY,
            ENCRYPTION_PREVIOUS_KEYS=PREVIOUS_KEY,
            LEGACY_ENCRYPTION_KEY="",
        )
        assert decrypt_secret(old_token.decode("ascii")) == "segreto"
        rotated = rotate_secret(old_token.decode("ascii"))

        app.config["ENCRYPTION_PREVIOUS_KEYS"] = ""
        assert decrypt_secret(rotated) == "segreto"
        with pytest.raises(SecretDecryptionError):
            decrypt_secret(old_token.decode("ascii"))


def test_cli_rotates_legacy_sha256_encryption(app, runner):
    with app.app_context():
        app.config.update(
            ENCRYPTION_KEY=PRIMARY_KEY,
            ENCRYPTION_PREVIOUS_KEYS="",
            LEGACY_ENCRYPTION_KEY=LEGACY_MATERIAL,
        )
        user = User(email="admin-rotation@example.it", profile_completed=True)
        user.roles.append(Role.query.filter_by(name="admin").one())
        db.session.add(user)
        db.session.flush()
        configuration = SmtpConfiguration(
            id=1,
            host="smtp.example.it",
            username="mailer@example.it",
            password_encrypted=_legacy_token("password SMTP"),
            from_email="mailer@example.it",
            updated_by_user_id=user.id,
        )
        db.session.add(configuration)
        db.session.commit()
        old_token = configuration.password_encrypted

    result = runner.invoke(args=["admin", "rotate-encryption-key"])

    assert result.exit_code == 0
    assert "ricifrata" in result.output
    with app.app_context():
        app.config["LEGACY_ENCRYPTION_KEY"] = ""
        rotated = db.session.get(SmtpConfiguration, 1).password_encrypted
        assert rotated != old_token
        assert decrypt_secret(rotated) == "password SMTP"
        with pytest.raises(SecretDecryptionError):
            decrypt_secret(old_token)


def test_generate_secrets_emits_a_real_fernet_key(runner):
    result = runner.invoke(args=["admin", "generate-secrets"])

    assert result.exit_code == 0
    values = dict(line.split("=", 1) for line in result.output.strip().splitlines())
    Fernet(values["MCORSI_ENCRYPTION_KEY"].encode("ascii"))
    Fernet(values["MCORSI_BACKUP_ENCRYPTION_KEY"].encode("ascii"))
    assert len(set(values.values())) == 5


def test_production_rejects_a_passphrase_as_encryption_key():
    with pytest.raises(RuntimeError, match="MCORSI_ENCRYPTION_KEY"):
        create_app(
            "production",
            {
                "SECRET_KEY": "s" * 40,
                "ENCRYPTION_KEY": "questa-non-e-una-chiave-fernet-ma-e-lunga",
                "OTP_PEPPER": "o" * 40,
                "MCP_TOKEN_PEPPER": "m" * 40,
            },
        )


def test_production_requires_a_dedicated_backup_key():
    with pytest.raises(RuntimeError, match="MCORSI_BACKUP_ENCRYPTION_KEY"):
        create_app(
            "production",
            {
                "SECRET_KEY": "s" * 40,
                "ENCRYPTION_KEY": PRIMARY_KEY,
                "BACKUP_ENCRYPTION_KEY": "",
                "OTP_PEPPER": "o" * 40,
                "MCP_TOKEN_PEPPER": "m" * 40,
            },
        )
