from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

import mcorsi.startup_secrets as startup_secrets
from mcorsi.services.secrets import is_fernet_key
from mcorsi.startup_secrets import (
    StartupSecretError,
    complete_environment,
    prepare_environment,
)


SECRET_NAMES = (
    "MCORSI_SECRET_KEY",
    "MCORSI_ENCRYPTION_KEY",
    "MCORSI_BACKUP_ENCRYPTION_KEY",
    "MCORSI_BACKUP_DECRYPTION_KEYS",
    "MCORSI_LEGACY_ENCRYPTION_KEY",
    "MCORSI_OTP_PEPPER",
    "MCORSI_MCP_TOKEN_PEPPER",
    "MCORSI_DATABASE_URL",
)


@pytest.fixture()
def startup_root():
    path = Path.cwd() / "instance" / "test-data" / f"startup-{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def _clear_environment(monkeypatch):
    for name in SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)


def _write_env(path: Path, *, encryption_key: str, backup_key: str = "") -> str:
    old_material = encryption_key
    path.write_text(
        "\n".join(
            [
                "MCORSI_SECRET_KEY=" + "s" * 48,
                f"MCORSI_ENCRYPTION_KEY='{encryption_key}'",
                f"MCORSI_BACKUP_ENCRYPTION_KEY='{backup_key}'",
                "MCORSI_OTP_PEPPER=" + "o" * 48,
                "MCORSI_MCP_TOKEN_PEPPER=" + "m" * 48,
                f"MCORSI_DATABASE_URL=sqlite:///{path.parent / 'instance' / 'mcorsi.sqlite3'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return old_material


def test_prepare_migrates_legacy_key_and_marks_backup_and_rotation(
    startup_root, monkeypatch
):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    database_path = startup_root / "instance" / "mcorsi.sqlite3"
    database_path.parent.mkdir()
    database_path.write_bytes(b"database")
    old_material = _write_env(env_path, encryption_key="vecchia passphrase con spazi")
    original = env_path.read_text(encoding="utf-8")

    assert prepare_environment(env_path, marker_path, startup_root) is True

    values = dotenv_values(env_path)
    assert values["MCORSI_LEGACY_ENCRYPTION_KEY"] == old_material
    assert is_fernet_key(values["MCORSI_ENCRYPTION_KEY"])
    assert is_fernet_key(values["MCORSI_BACKUP_ENCRYPTION_KEY"])
    assert values["MCORSI_ENCRYPTION_KEY"] != values["MCORSI_BACKUP_ENCRYPTION_KEY"]
    assert (startup_root / ".env.pre-secret-migration").read_text(encoding="utf-8") == original
    assert json.loads(marker_path.read_text(encoding="utf-8")) == {
        "backup_required": True,
        "remove_legacy": True,
        "rotation_required": True,
    }

    complete_environment(env_path, marker_path)

    assert "MCORSI_LEGACY_ENCRYPTION_KEY" not in dotenv_values(env_path)
    assert not marker_path.exists()


def test_prepare_generates_missing_otp_and_mcp_secrets(startup_root, monkeypatch):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    old_secret = "segreto-sessione-legacy-" + "s" * 32
    env_path.write_text(
        f"MCORSI_SECRET_KEY='{old_secret}'\n",
        encoding="utf-8",
    )

    assert prepare_environment(env_path, marker_path, startup_root) is True

    values = dotenv_values(env_path)
    configured = {
        values["MCORSI_SECRET_KEY"],
        values["MCORSI_OTP_PEPPER"],
        values["MCORSI_MCP_TOKEN_PEPPER"],
        values["MCORSI_ENCRYPTION_KEY"],
        values["MCORSI_BACKUP_ENCRYPTION_KEY"],
    }
    assert len(configured) == 5
    assert values["MCORSI_SECRET_KEY"] == old_secret
    assert len(values["MCORSI_OTP_PEPPER"]) >= 32
    assert len(values["MCORSI_MCP_TOKEN_PEPPER"]) >= 32
    assert values["MCORSI_LEGACY_ENCRYPTION_KEY"] == old_secret


def test_prepare_replaces_placeholder_stable_secrets(startup_root, monkeypatch):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    env_path.write_text(
        "\n".join(
            [
                "MCORSI_SECRET_KEY=cambia-questo-valore",
                "MCORSI_OTP_PEPPER=usa-un-terzo-valore-lungo-e-casuale",
                "MCORSI_MCP_TOKEN_PEPPER=usa-un-quarto-valore-lungo-e-casuale",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert prepare_environment(env_path, marker_path, startup_root) is True

    values = dotenv_values(env_path)
    stable_values = [values[name] for name in startup_secrets.STABLE_SECRET_NAMES]
    assert all(len(value) >= 32 for value in stable_values)
    assert len(set(stable_values)) == len(stable_values)
    assert values["MCORSI_LEGACY_ENCRYPTION_KEY"] == "cambia-questo-valore"


def test_prepare_creates_a_secure_env_when_it_is_missing(startup_root, monkeypatch):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"

    assert prepare_environment(env_path, marker_path, startup_root) is True

    values = dotenv_values(env_path)
    configured = [
        values["MCORSI_SECRET_KEY"],
        values["MCORSI_ENCRYPTION_KEY"],
        values["MCORSI_BACKUP_ENCRYPTION_KEY"],
        values["MCORSI_OTP_PEPPER"],
        values["MCORSI_MCP_TOKEN_PEPPER"],
    ]
    assert all(len(value) >= 32 for value in configured)
    assert len(set(configured)) == len(configured)
    assert values["MCORSI_LEGACY_ENCRYPTION_KEY"] == "development-only-change-me"
    assert not (startup_root / ".env.pre-secret-migration").exists()


def test_prepare_adds_only_backup_key_when_primary_is_already_valid(
    startup_root, monkeypatch
):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    primary = Fernet.generate_key().decode("ascii")
    _write_env(env_path, encryption_key=primary)

    assert prepare_environment(env_path, marker_path, startup_root) is True

    values = dotenv_values(env_path)
    assert values["MCORSI_ENCRYPTION_KEY"] == primary
    assert is_fernet_key(values["MCORSI_BACKUP_ENCRYPTION_KEY"])
    assert "MCORSI_LEGACY_ENCRYPTION_KEY" not in values
    assert json.loads(marker_path.read_text(encoding="utf-8"))["rotation_required"] is False


def test_prepare_separates_a_backup_key_reused_from_the_primary(
    startup_root, monkeypatch
):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    shared_key = Fernet.generate_key().decode("ascii")
    _write_env(env_path, encryption_key=shared_key, backup_key=shared_key)

    assert prepare_environment(env_path, marker_path, startup_root) is True

    values = dotenv_values(env_path)
    assert values["MCORSI_ENCRYPTION_KEY"] == shared_key
    assert values["MCORSI_BACKUP_ENCRYPTION_KEY"] != shared_key
    assert values["MCORSI_BACKUP_DECRYPTION_KEYS"] == shared_key
    assert json.loads(marker_path.read_text(encoding="utf-8"))["rotation_required"] is False


def test_prepare_refuses_to_override_an_invalid_process_secret(
    startup_root, monkeypatch
):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    _write_env(env_path, encryption_key=Fernet.generate_key().decode("ascii"))
    original = env_path.read_text(encoding="utf-8")
    monkeypatch.setenv("MCORSI_ENCRYPTION_KEY", "chiave-esterna-non-valida")

    with pytest.raises(StartupSecretError, match="ambiente del processo"):
        prepare_environment(env_path, marker_path, startup_root)

    assert env_path.read_text(encoding="utf-8") == original
    assert not marker_path.exists()


def test_prepare_refuses_to_override_an_invalid_stable_process_secret(
    startup_root, monkeypatch
):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    _write_env(
        env_path,
        encryption_key=Fernet.generate_key().decode("ascii"),
        backup_key=Fernet.generate_key().decode("ascii"),
    )
    original = env_path.read_text(encoding="utf-8")
    monkeypatch.setenv("MCORSI_OTP_PEPPER", "pepper-esterno-corto")

    with pytest.raises(StartupSecretError, match="ambiente del processo"):
        prepare_environment(env_path, marker_path, startup_root)

    assert env_path.read_text(encoding="utf-8") == original
    assert not marker_path.exists()


def test_prepare_restores_env_if_a_write_fails(startup_root, monkeypatch):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    _write_env(env_path, encryption_key="vecchia passphrase")
    original = env_path.read_text(encoding="utf-8")
    real_set_key = startup_secrets.set_key
    calls = 0

    def failing_set_key(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("scrittura interrotta")
        return real_set_key(*args, **kwargs)

    monkeypatch.setattr(startup_secrets, "set_key", failing_set_key)

    with pytest.raises(OSError, match="scrittura interrotta"):
        prepare_environment(env_path, marker_path, startup_root)

    assert env_path.read_text(encoding="utf-8") == original
    assert not marker_path.exists()


def test_complete_refuses_a_corrupted_migration_marker(startup_root, monkeypatch):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    marker_path.parent.mkdir()
    marker_path.write_text(
        json.dumps(
            {
                "backup_required": "yes",
                "remove_legacy": True,
                "rotation_required": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StartupSecretError, match="non è valido"):
        complete_environment(env_path, marker_path)

    assert marker_path.exists()


def test_prepare_leaves_a_secure_environment_untouched(startup_root, monkeypatch):
    _clear_environment(monkeypatch)
    env_path = startup_root / ".env"
    marker_path = startup_root / "instance" / ".secret-migration.json"
    _write_env(
        env_path,
        encryption_key=Fernet.generate_key().decode("ascii"),
        backup_key=Fernet.generate_key().decode("ascii"),
    )
    original = env_path.read_text(encoding="utf-8")

    assert prepare_environment(env_path, marker_path, startup_root) is False

    assert env_path.read_text(encoding="utf-8") == original
    assert not marker_path.exists()
