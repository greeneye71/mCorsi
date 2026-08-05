from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import secrets
import zipfile
from flask import Flask, current_app
from flask.cli import with_appcontext
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import McpAccessToken, Role, User, normalize_email
from .services.audit import record_event
from .services.backup import create_backup, restore_backup, verify_backup
from .services.mcp_access import MCP_SCOPES, create_access_token
from .services.notifications import deliver_pending, enqueue_reminders


ROLE_NAMES = ("admin", "operator", "participant", "company_contact", "service")


def _prompt_password(label: str = "Password") -> str:
    while True:
        password = click.prompt(label, hide_input=True, confirmation_prompt=True)
        if len(password) >= 12:
            return password
        click.echo("La password deve contenere almeno 12 caratteri.", err=True)


def ensure_roles() -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name in ROLE_NAMES:
        role = Role.query.filter_by(name=name).first()
        if role is None:
            role = Role(name=name)
            db.session.add(role)
        roles[name] = role
    db.session.flush()
    return roles


def register_commands(app: Flask) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(admin_group)
    app.cli.add_command(backup_group)
    app.cli.add_command(notifications_group)
    app.cli.add_command(mcp_group)


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


def _create_staff(email: str, role_name: str, password: str) -> User:
    ensure_roles()
    normalized = normalize_email(email)
    if User.query.filter_by(email=normalized).first() is not None:
        raise click.ClickException("Esiste già un utente con questa email.")
    user = User(email=normalized, profile_completed=True)
    user.set_password(password)
    user.roles.append(Role.query.filter_by(name=role_name).one())
    if role_name == "admin":
        user.roles.append(Role.query.filter_by(name="operator").one())
    db.session.add(user)
    record_event(
        "admin.user_created_cli",
        target_type="user",
        target_id=user.id,
        detail={"email": user.email, "role": role_name},
    )
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise click.ClickException("Impossibile creare l'utente.") from exc
    return user


@admin_group.command("create")
@click.option("--email", prompt=True, help="Email del nuovo amministratore.")
@with_appcontext
def create_admin(email: str) -> None:
    """Crea un amministratore con ruolo operatore incluso."""
    password = _prompt_password()
    user = _create_staff(email, "admin", password)
    click.echo(f"Amministratore creato: {user.email}")


@admin_group.command("create-operator")
@click.option("--email", prompt=True, help="Email del nuovo operatore.")
@with_appcontext
def create_operator(email: str) -> None:
    """Crea un operatore."""
    password = _prompt_password()
    user = _create_staff(email, "operator", password)
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
        click.echo(f"{user.email}\t{roles}\t{state}")


@admin_group.command("generate-secrets")
def generate_secrets() -> None:
    """Genera i segreti distinti da copiare nel file .env."""
    click.echo(f"MCORSI_SECRET_KEY={secrets.token_urlsafe(48)}")
    click.echo(f"MCORSI_ENCRYPTION_KEY={secrets.token_urlsafe(48)}")
    click.echo(f"MCORSI_OTP_PEPPER={secrets.token_urlsafe(48)}")
    click.echo(f"MCORSI_MCP_TOKEN_PEPPER={secrets.token_urlsafe(48)}")


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
@with_appcontext
def backup_verify(archive: Path) -> None:
    """Verifica struttura e checksum di un backup."""
    try:
        manifest = verify_backup(archive)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Backup valido: {manifest['created_at']} · {len(manifest['files'])} file"
    )


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
@with_appcontext
def backup_restore(archive: Path, server_stopped: bool) -> None:
    """Ripristina database e storage creando prima un backup di sicurezza."""
    if not server_stopped:
        raise click.ClickException(
            "Ferma web server e processi pianificati, poi ripeti con --server-stopped."
        )
    try:
        manifest = restore_backup(archive, safety_backup=True)
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
