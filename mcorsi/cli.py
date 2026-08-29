from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import zipfile
from flask import Flask, current_app
from flask.cli import with_appcontext
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import McpAccessToken, Role, SmtpConfiguration, User, normalize_email
from .services.audit import record_event
from .services.backup import (
    create_backup,
    encrypt_legacy_backup,
    restore_backup,
    verify_backup,
)
from .services.mcp_access import MCP_SCOPES, create_access_token
from .services.notifications import deliver_pending, enqueue_reminders
from .services.passwords import PASSWORD_POLICY_MESSAGE, password_is_valid
from .services.secrets import (
    SecretDecryptionError,
    generate_secret_values,
    has_decryption_fallbacks,
    rotate_secret,
)
from .services.versioning import ensure_system_version, version_information


ROLE_NAMES = ("admin", "operator", "participant", "company_contact", "service")


def _prompt_password(label: str = "Password") -> str:
    while True:
        password = click.prompt(label, hide_input=True, confirmation_prompt=True)
        if password_is_valid(password):
            return password
        click.echo(PASSWORD_POLICY_MESSAGE, err=True)


def ensure_roles() -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name in ROLE_NAMES:
        role = Role.query.filter_by(name=name).first()
        if role is None:
            role = Role(name=name)
            db.session.add(role)
        roles[name] = role
    db.session.flush()
    ensure_system_version()
    return roles


def register_commands(app: Flask) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(admin_group)
    app.cli.add_command(backup_group)
    app.cli.add_command(notifications_group)
    app.cli.add_command(mcp_group)
    app.cli.add_command(version_command)


@click.command("version")
@with_appcontext
def version_command() -> None:
    """Mostra versioni dell'applicazione, del database e di Alembic."""
    try:
        information = version_information()
    except Exception as exc:
        db.session.rollback()
        raise click.ClickException(
            "Metadati di versione non disponibili: esegui prima flask db upgrade."
        ) from exc
    click.echo(f"mCorsi {information['application_version']}")
    click.echo(
        f"Database {information['database_version']} "
        f"(richiesto {information['required_database_version']})"
    )
    click.echo(f"Alembic {information['alembic_revision'] or 'non inizializzato'}")
    click.echo("Compatibilità: " + ("ok" if information["compatible"] else "migrazione richiesta"))


@click.command("init-db")
@with_appcontext
def init_db_command() -> None:
    """Applica le migrazioni e crea i ruoli di sistema."""
    upgrade()
    ensure_roles()
    db.session.commit()
    click.echo("Database inizializzato.")


@click.group("admin")
def admin_group() -> None:
    """Gestione amministrativa degli utenti."""


def _create_staff(email: str, role_name: str, password: str, name: str) -> User:
    ensure_roles()
    normalized = normalize_email(email)
    normalized_name = name.strip()
    if not normalized_name:
        raise click.ClickException("Il nome è obbligatorio.")
    if User.query.filter_by(email=normalized).first() is not None:
        raise click.ClickException("Esiste già un utente con questa email.")
    user = User(email=normalized, first_name=normalized_name, profile_completed=True)
    user.set_password(password)
    user.roles.append(Role.query.filter_by(name=role_name).one())
    if role_name == "admin":
        user.roles.append(Role.query.filter_by(name="operator").one())
    db.session.add(user)
    record_event(
        "admin.user_created_cli",
        target_type="user",
        target_id=user.id,
        detail={"email": user.email, "name": user.first_name, "role": role_name},
    )
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise click.ClickException("Impossibile creare l'utente.") from exc
    return user


@admin_group.command("create")
@click.option("--email", prompt=True, help="Email del nuovo amministratore.")
@click.option("--name", prompt="Nome", help="Nome mostrato nell'interfaccia.")
@with_appcontext
def create_admin(email: str, name: str) -> None:
    """Crea un amministratore con ruolo operatore incluso."""
    password = _prompt_password()
    user = _create_staff(email, "admin", password, name)
    click.echo(f"Amministratore creato: {user.email}")


@admin_group.command("bootstrap")
@click.option("--email", default=None, help="Email del primo amministratore.")
@click.option("--name", default=None, help="Nome mostrato nell'interfaccia.")
@with_appcontext
def bootstrap_admin(email: str | None, name: str | None) -> None:
    """Crea il primo amministratore solo quando non ne esiste già uno."""
    ensure_roles()
    existing = User.query.filter(User.roles.any(name="admin")).first()
    if existing is not None:
        click.echo(f"Amministratore già configurato: {existing.email}")
        return
    selected_email = email or click.prompt("Email del primo amministratore")
    selected_name = name or click.prompt("Nome del primo amministratore")
    password = _prompt_password()
    user = _create_staff(selected_email, "admin", password, selected_name)
    click.echo(f"Amministratore creato: {user.email}")


@admin_group.command("create-operator")
@click.option("--email", prompt=True, help="Email del nuovo operatore.")
@click.option("--name", prompt="Nome", help="Nome mostrato nell'interfaccia.")
@with_appcontext
def create_operator(email: str, name: str) -> None:
    """Crea un operatore."""
    password = _prompt_password()
    user = _create_staff(email, "operator", password, name)
    click.echo(f"Operatore creato: {user.email}")


@admin_group.command("set-password")
@click.argument("email")
@with_appcontext
def set_password(email: str) -> None:
    """Imposta una nuova password senza mostrarla nella shell."""
    user = User.query.filter_by(email=normalize_email(email)).first()
    if user is None or not user.has_role("admin", "operator"):
        raise click.ClickException("Operatore o amministratore non trovato.")
    password = _prompt_password("Nuova password")
    user.set_password(password)
    record_event(
        "admin.password_changed_cli",
        target_type="user",
        target_id=user.id,
        detail={"email": user.email},
    )
    db.session.commit()
    click.echo(f"Password aggiornata: {user.email}")


@admin_group.command("disable-user")
@click.argument("email")
@with_appcontext
def disable_user(email: str) -> None:
    """Disabilita un account senza cancellarlo."""
    user = User.query.filter_by(email=normalize_email(email)).first()
    if user is None:
        raise click.ClickException("Utente non trovato.")
    user.is_active = False
    record_event("admin.user_disabled_cli", target_type="user", target_id=user.id)
    db.session.commit()
    click.echo(f"Utente disabilitato: {user.email}")


@admin_group.command("list-users")
@with_appcontext
def list_users() -> None:
    """Elenca gli utenti e i relativi ruoli."""
    users = User.query.order_by(User.email).all()
    if not users:
        click.echo("Nessun utente.")
        return
    for user in users:
        roles = ",".join(sorted(role.name for role in user.roles))
        state = "attivo" if user.is_active else "disabilitato"
        click.echo(f"{user.display_name}\t{user.email}\t{roles}\t{state}")


@admin_group.command("generate-secrets")
def generate_secrets() -> None:
    """Genera i segreti distinti da copiare nel file .env."""
    for name, value in generate_secret_values().items():
        click.echo(f"{name}={value}")


@admin_group.command("rotate-encryption-key")
@with_appcontext
def rotate_encryption_key() -> None:
    """Ricifra i segreti persistiti con la chiave Fernet primaria."""
    if not has_decryption_fallbacks():
        raise click.ClickException(
            "Configura MCORSI_ENCRYPTION_PREVIOUS_KEYS o MCORSI_LEGACY_ENCRYPTION_KEY."
        )
    configuration = db.session.get(SmtpConfiguration, 1)
    if configuration is None or not configuration.password_encrypted:
        click.echo("Nessuna password SMTP da ruotare.")
        return
    try:
        configuration.password_encrypted = rotate_secret(
            configuration.password_encrypted
        )
    except SecretDecryptionError as exc:
        db.session.rollback()
        raise click.ClickException(str(exc)) from exc
    record_event(
        "admin.encryption_key_rotated_cli",
        target_type="smtp_configuration",
        target_id=str(configuration.id),
    )
    db.session.commit()
    click.echo("Password SMTP ricifrata con MCORSI_ENCRYPTION_KEY.")


@click.group("mcp")
def mcp_group() -> None:
    """Gestisce le credenziali del server MCP."""


@mcp_group.command("token-create")
@click.option("--name", prompt=True, help="Nome descrittivo del client AI.")
@click.option(
    "--creator-email", required=True, help="Amministratore responsabile del token."
)
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    type=click.Choice(MCP_SCOPES, case_sensitive=True),
    required=True,
)
@click.option("--days", type=click.IntRange(1, 3650), default=365, show_default=True)
@with_appcontext
def mcp_token_create(name: str, creator_email: str, scopes: tuple[str, ...], days: int) -> None:
    """Crea un token, mostrandone il valore soltanto una volta."""
    creator = User.query.filter_by(email=normalize_email(creator_email)).first()
    if creator is None or not creator.has_role("admin") or not creator.is_active:
        raise click.ClickException("Amministratore attivo non trovato.")
    raw_token, access = create_access_token(
        name=name,
        scopes=list(scopes),
        creator=creator,
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.session.commit()
    click.echo(f"Token creato: {access.name} ({access.token_prefix})")
    click.echo("Conservalo ora: non sarà più visualizzato.")
    click.echo(raw_token)


@mcp_group.command("token-list")
@with_appcontext
def mcp_token_list() -> None:
    """Elenca token, permessi, scadenza e ultimo utilizzo."""
    tokens = McpAccessToken.query.order_by(McpAccessToken.created_at.desc()).all()
    if not tokens:
        click.echo("Nessun token MCP.")
        return
    for token in tokens:
        state = "attivo" if token.is_active else "revocato"
        expiry = token.expires_at.isoformat() if token.expires_at else "mai"
        used = token.last_used_at.isoformat() if token.last_used_at else "mai"
        click.echo(
            f"{token.token_prefix}\t{token.name}\t{state}\t{','.join(token.scopes)}"
            f"\tscadenza={expiry}\tultimo_uso={used}"
        )


@mcp_group.command("token-revoke")
@click.argument("prefix")
@with_appcontext
def mcp_token_revoke(prefix: str) -> None:
    """Revoca immediatamente un token tramite il suo prefisso."""
    token = McpAccessToken.query.filter_by(token_prefix=prefix.strip()).first()
    if token is None:
        raise click.ClickException("Token non trovato.")
    token.is_active = False
    record_event(
        "mcp.token_revoked",
        target_type="mcp_access_token",
        target_id=token.id,
        detail={"name": token.name, "prefix": token.token_prefix},
    )
    db.session.commit()
    click.echo(f"Token revocato: {token.token_prefix}")


@click.group("backup")
def backup_group() -> None:
    """Crea e verifica backup locali."""


@backup_group.command("create")
@click.option("--destination", type=click.Path(path_type=Path), default=None)
@with_appcontext
def backup_create(destination: Path | None) -> None:
    """Crea un backup coerente del database e dello storage."""
    try:
        path = create_backup(destination)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Backup creato e verificato: {path}")


@backup_group.command("verify")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--allow-legacy-unencrypted", is_flag=True)
@with_appcontext
def backup_verify(archive: Path, allow_legacy_unencrypted: bool) -> None:
    """Verifica struttura e checksum di un backup."""
    try:
        manifest = verify_backup(
            archive, allow_legacy_unencrypted=allow_legacy_unencrypted
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Backup valido: {manifest['created_at']} · {len(manifest['files'])} file"
    )


@backup_group.command("encrypt-legacy")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--destination", type=click.Path(path_type=Path), default=None)
@with_appcontext
def backup_encrypt_legacy(archive: Path, destination: Path | None) -> None:
    """Crea una copia cifrata di un backup legacy senza cancellare l'originale."""
    try:
        output = encrypt_legacy_backup(archive, destination)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Backup legacy convertito e verificato: {output}")


@backup_group.command("list")
@with_appcontext
def backup_list() -> None:
    """Elenca i backup nella destinazione configurata."""
    folder = Path(current_app.config["BACKUP_PATH"])
    archives = sorted(folder.glob("*.mcbackup"), reverse=True)
    if not archives:
        click.echo("Nessun backup disponibile.")
        return
    for archive in archives:
        click.echo(f"{archive.name}\t{archive.stat().st_size} byte")


@backup_group.command("restore")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--server-stopped",
    is_flag=True,
    help="Conferma che web server, worker e scheduler sono fermi.",
)
@click.option("--allow-legacy-unencrypted", is_flag=True)
@with_appcontext
def backup_restore(
    archive: Path, server_stopped: bool, allow_legacy_unencrypted: bool
) -> None:
    """Ripristina database e storage creando prima un backup di sicurezza."""
    if not server_stopped:
        raise click.ClickException(
            "Ferma web server e processi pianificati, poi ripeti con --server-stopped."
        )
    try:
        manifest = restore_backup(
            archive,
            safety_backup=True,
            allow_legacy_unencrypted=allow_legacy_unencrypted,
        )
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Ripristino completato dal backup del {manifest['created_at']}.")


@click.group("notifications")
def notifications_group() -> None:
    """Accoda e invia promemoria email."""


@notifications_group.command("enqueue")
@with_appcontext
def notifications_enqueue() -> None:
    """Accoda i promemoria previsti per oggi."""
    counts = enqueue_reminders()
    click.echo(f"Messaggi accodati: {sum(counts.values())}")


@notifications_group.command("send")
@click.option("--limit", type=click.IntRange(1, 500), default=50)
@with_appcontext
def notifications_send(limit: int) -> None:
    """Invia i messaggi pronti nella coda."""
    result = deliver_pending(limit=limit)
    click.echo(
        f"Inviati: {result['sent']} · rinviati: {result['deferred']} · falliti: {result['failed']}"
    )


@notifications_group.command("run")
@click.option("--limit", type=click.IntRange(1, 500), default=50)
@with_appcontext
def notifications_run(limit: int) -> None:
    """Accoda i promemoria e invia la coda, per scheduler/cron."""
    queued = enqueue_reminders()
    result = deliver_pending(limit=limit)
    click.echo(
        f"Accodati: {sum(queued.values())} · inviati: {result['sent']} · rinviati: {result['deferred']} · falliti: {result['failed']}"
    )
