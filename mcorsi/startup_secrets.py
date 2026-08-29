from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key, unset_key

from .services.secrets import is_fernet_key


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_MARKER_PATH = PROJECT_ROOT / "instance" / ".secret-migration.json"
PLACEHOLDER_SECRETS = {
    "development-only-change-me",
    "cambia-questo-valore",
    "usa-un-secondo-valore-lungo-e-casuale",
    "usa-una-chiave-fernet-dedicata-ai-backup",
    "usa-un-terzo-valore-lungo-e-casuale",
    "usa-un-quarto-valore-lungo-e-casuale",
}
STABLE_SECRET_NAMES = (
    "MCORSI_SECRET_KEY",
    "MCORSI_OTP_PEPPER",
    "MCORSI_MCP_TOKEN_PEPPER",
)


class StartupSecretError(RuntimeError):
    pass


def _fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _values(env_path: Path) -> dict[str, str]:
    return {
        key: value
        for key, value in dotenv_values(env_path).items()
        if value is not None
    }


def _effective(values: dict[str, str], name: str, default: str = "") -> str:
    return os.environ.get(name, values.get(name, default))


def _validate_stable_secrets(values: dict[str, str]) -> None:
    configured = {name: _effective(values, name) for name in STABLE_SECRET_NAMES}
    invalid = [
        name
        for name, value in configured.items()
        if value in PLACEHOLDER_SECRETS or len(value) < 32
    ]
    if len(set(configured.values())) != len(configured):
        invalid.extend(configured)
    if invalid:
        raise StartupSecretError(
            "La migrazione automatica non modifica segreti di sessione, OTP o MCP. "
            "Configura valori lunghi e distinti per: " + ", ".join(sorted(set(invalid)))
        )


def _backup_env(env_path: Path) -> Path | None:
    if not env_path.exists():
        return None
    base = env_path.with_name(f"{env_path.name}.pre-secret-migration")
    destination = base
    suffix = 1
    while destination.exists():
        destination = base.with_name(f"{base.name}.{suffix}")
        suffix += 1
    shutil.copy2(env_path, destination)
    if os.name != "nt":
        destination.chmod(0o600)
    return destination


def _database_exists(values: dict[str, str], project_root: Path) -> bool:
    default_path = project_root / "instance" / "mcorsi-v2.sqlite3"
    uri = _effective(values, "MCORSI_DATABASE_URL", f"sqlite:///{default_path}")
    prefix = "sqlite:///"
    if not uri.startswith(prefix) or uri.endswith(":memory:"):
        return False
    database_path = Path(uri.removeprefix(prefix))
    if not database_path.is_absolute():
        database_path = project_root / database_path
    return database_path.resolve().is_file()


def _write_marker(
    marker_path: Path,
    *,
    backup_required: bool,
    remove_legacy: bool,
    rotation_required: bool,
) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            {
                "backup_required": backup_required,
                "remove_legacy": remove_legacy,
                "rotation_required": rotation_required,
            }
        ),
        encoding="utf-8",
    )
    if os.name != "nt":
        marker_path.chmod(0o600)


def prepare_environment(
    env_path: Path = DEFAULT_ENV_PATH,
    marker_path: Path = DEFAULT_MARKER_PATH,
    project_root: Path = PROJECT_ROOT,
) -> bool:
    if env_path.is_symlink():
        raise StartupSecretError("Il file .env non può essere un collegamento simbolico.")

    values = _values(env_path)
    _validate_stable_secrets(values)
    secret_key = _effective(values, "MCORSI_SECRET_KEY")
    primary = _effective(values, "MCORSI_ENCRYPTION_KEY", secret_key)
    backup_key = _effective(values, "MCORSI_BACKUP_ENCRYPTION_KEY")
    legacy = _effective(values, "MCORSI_LEGACY_ENCRYPTION_KEY")
    stable_values = {_effective(values, name) for name in STABLE_SECRET_NAMES}
    changes: dict[str, str] = {}
    remove_legacy = False
    primary_requires_migration = (
        not is_fernet_key(primary)
        or primary in PLACEHOLDER_SECRETS
        or primary in stable_values
    )

    if primary_requires_migration:
        if "MCORSI_ENCRYPTION_KEY" in os.environ:
            raise StartupSecretError(
                "MCORSI_ENCRYPTION_KEY proviene dall'ambiente del processo e non è "
                "una chiave Fernet valida: aggiornala nel servizio che avvia mCorsi."
            )
        if not legacy:
            changes["MCORSI_LEGACY_ENCRYPTION_KEY"] = primary
            remove_legacy = True
        changes["MCORSI_ENCRYPTION_KEY"] = _fernet_key()

    backup_requires_migration = (
        not is_fernet_key(backup_key)
        or backup_key in PLACEHOLDER_SECRETS
        or backup_key in stable_values
        or backup_key == primary
    )
    if backup_requires_migration:
        if "MCORSI_BACKUP_ENCRYPTION_KEY" in os.environ:
            raise StartupSecretError(
                "MCORSI_BACKUP_ENCRYPTION_KEY proviene dall'ambiente del processo e "
                "non è valida: aggiornala nel servizio che avvia mCorsi."
            )
        if is_fernet_key(backup_key):
            previous_backup_keys = _effective(
                values, "MCORSI_BACKUP_DECRYPTION_KEYS"
            )
            previous = [
                item.strip() for item in previous_backup_keys.split(",") if item.strip()
            ]
            if backup_key not in previous:
                previous.append(backup_key)
                changes["MCORSI_BACKUP_DECRYPTION_KEYS"] = ",".join(previous)
        changes["MCORSI_BACKUP_ENCRYPTION_KEY"] = _fernet_key()

    pending_legacy = bool(values.get("MCORSI_LEGACY_ENCRYPTION_KEY"))
    if not changes and not pending_legacy:
        return marker_path.exists()

    env_existed = env_path.exists()
    backup_path = _backup_env(env_path) if changes else None
    try:
        for name, value in changes.items():
            set_key(env_path, name, value, quote_mode="always")
        if os.name != "nt":
            env_path.chmod(0o600)

        updated = _values(env_path)
        configured = {
            "MCORSI_SECRET_KEY": _effective(updated, "MCORSI_SECRET_KEY"),
            "MCORSI_ENCRYPTION_KEY": _effective(updated, "MCORSI_ENCRYPTION_KEY"),
            "MCORSI_BACKUP_ENCRYPTION_KEY": _effective(
                updated, "MCORSI_BACKUP_ENCRYPTION_KEY"
            ),
            "MCORSI_OTP_PEPPER": _effective(updated, "MCORSI_OTP_PEPPER"),
            "MCORSI_MCP_TOKEN_PEPPER": _effective(updated, "MCORSI_MCP_TOKEN_PEPPER"),
        }
        if (
            not is_fernet_key(configured["MCORSI_ENCRYPTION_KEY"])
            or not is_fernet_key(configured["MCORSI_BACKUP_ENCRYPTION_KEY"])
            or len(set(configured.values())) != len(configured)
        ):
            raise StartupSecretError(
                "La configurazione generata non ha superato la verifica."
            )

        _write_marker(
            marker_path,
            backup_required=_database_exists(updated, project_root),
            remove_legacy=remove_legacy or pending_legacy,
            rotation_required=primary_requires_migration or pending_legacy,
        )
    except Exception:
        marker_path.unlink(missing_ok=True)
        if backup_path is not None:
            shutil.copy2(backup_path, env_path)
        elif changes and not env_existed:
            env_path.unlink(missing_ok=True)
        raise
    print("Configurazione di cifratura aggiornata senza esporre i nuovi segreti.")
    if backup_path:
        print(f"Copia protetta della configurazione: {backup_path.name}")
    return True


def _marker(marker_path: Path) -> dict[str, bool] | None:
    if not marker_path.exists():
        return None
    try:
        value = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StartupSecretError("Il marcatore della migrazione dei segreti è danneggiato.") from exc
    required_fields = ("backup_required", "remove_legacy", "rotation_required")
    if not isinstance(value, dict) or any(
        not isinstance(value.get(field), bool) for field in required_fields
    ):
        raise StartupSecretError("Il marcatore della migrazione dei segreti non è valido.")
    return value


def complete_environment(
    env_path: Path = DEFAULT_ENV_PATH,
    marker_path: Path = DEFAULT_MARKER_PATH,
) -> None:
    marker = _marker(marker_path)
    if marker is None:
        return
    remove_legacy = marker["remove_legacy"]
    if remove_legacy and env_path.exists():
        unset_key(env_path, "MCORSI_LEGACY_ENCRYPTION_KEY")
    marker_path.unlink()
    if remove_legacy:
        print("Migrazione dei segreti completata; fallback legacy rimosso.")
    else:
        print("Aggiornamento dei segreti completato.")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepara i segreti di avvio di mCorsi.")
    parser.add_argument(
        "command",
        choices=("prepare", "pending", "needs-backup", "needs-rotation", "complete"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_environment()
            return 0
        marker = _marker(DEFAULT_MARKER_PATH)
        if args.command == "pending":
            return 0 if marker is not None else 1
        if args.command == "needs-backup":
            return 0 if marker and marker.get("backup_required") else 1
        if args.command == "needs-rotation":
            return 0 if marker and marker.get("rotation_required") else 1
        complete_environment()
        return 0
    except StartupSecretError as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
