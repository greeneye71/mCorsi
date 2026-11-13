from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _production_cookie_flags(value: str | None) -> str:
    environment = os.environ.copy()
    if value is None:
        environment.pop("MCORSI_COOKIE_SECURE", None)
    else:
        environment["MCORSI_COOKIE_SECURE"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from mcorsi.config import ProductionConfig; "
                "print(ProductionConfig.SESSION_COOKIE_SECURE, "
                "ProductionConfig.REMEMBER_COOKIE_SECURE)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_production_cookie_security_defaults_to_https():
    assert _production_cookie_flags(None) == "True True"


def test_production_cookie_security_can_be_disabled_explicitly_for_lan_http():
    assert _production_cookie_flags("false") == "False False"


def test_instance_path_defaults_to_project_and_accepts_absolute_override(tmp_path):
    from mcorsi.config import BASE_DIR, instance_dir

    assert instance_dir({}) == BASE_DIR / "instance"
    assert instance_dir({"MCORSI_INSTANCE_PATH": str(tmp_path)}) == tmp_path


def test_instance_path_rejects_relative_values():
    import pytest

    from mcorsi.config import instance_dir

    with pytest.raises(RuntimeError, match="assoluto"):
        instance_dir({"MCORSI_INSTANCE_PATH": "instance"})


def test_app_uses_configured_instance_path(tmp_path, monkeypatch):
    from mcorsi import create_app

    target = tmp_path / "istanza"
    monkeypatch.setenv("MCORSI_INSTANCE_PATH", str(target))
    app = create_app(
        "testing",
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "PRIVATE_STORAGE_PATH": str(tmp_path / "storage"),
            "BACKUP_PATH": str(tmp_path / "backups"),
        },
    )
    assert Path(app.instance_path) == target
    assert target.is_dir()


def test_startup_marker_follows_instance_path(tmp_path, monkeypatch):
    from mcorsi import startup_secrets

    monkeypatch.setenv("MCORSI_INSTANCE_PATH", str(tmp_path))
    assert startup_secrets._default_marker_path(tmp_path / "missing.env") == (
        tmp_path / ".secret-migration.json"
    )


def test_wsgi_loads_external_env_file_before_reading_config(tmp_path):
    # Nel container il file .env sta in /config: deve essere caricato prima che
    # mcorsi.config legga os.environ, altrimenti i segreti risultano mancanti.
    from cryptography.fernet import Fernet
    import secrets as std_secrets

    env_file = tmp_path / "config" / ".env"
    env_file.parent.mkdir()
    env_file.write_text(
        "\n".join(
            [
                f"MCORSI_SECRET_KEY={std_secrets.token_urlsafe(48)}",
                f"MCORSI_OTP_PEPPER={std_secrets.token_urlsafe(48)}",
                f"MCORSI_MCP_TOKEN_PEPPER={std_secrets.token_urlsafe(48)}",
                f"MCORSI_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
                f"MCORSI_BACKUP_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    environment = {k: v for k, v in os.environ.items() if not k.startswith("MCORSI_")}
    data = tmp_path / "data"
    environment.update(
        {
            "MCORSI_ENV": "production",
            "MCORSI_ENV_FILE": str(env_file),
            "MCORSI_INSTANCE_PATH": str(data / "instance"),
            "MCORSI_BACKUP_PATH": str(tmp_path / "backups"),
            "MCORSI_STORAGE_PATH": str(data / "instance" / "storage"),
            "MCORSI_DATABASE_URL": "sqlite:///" + (data / "db.sqlite3").as_posix(),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import wsgi"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
