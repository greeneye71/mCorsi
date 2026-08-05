from __future__ import annotations

from datetime import timezone
from functools import wraps
from urllib.parse import urlsplit

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import create_app
from .services.mcp_access import verify_access_token
from .services.mcp_tools import (
    enqueue_reminders_data,
    expiring_certificates_data,
    get_course_data,
    list_courses_data,
    notification_status_data,
    participant_training_data,
    pending_admissions_data,
    record_tool_call,
    require_scope,
)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class DatabaseTokenVerifier(TokenVerifier):
    def __init__(self, flask_app):
        self.flask_app = flask_app

    async def verify_token(self, token: str) -> AccessToken | None:
        with self.flask_app.app_context():
            access = verify_access_token(token)
            if access is None:
                return None
            expiry = access.expires_at
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return AccessToken(
                token=token,
                client_id=access.id,
                scopes=list(access.scopes),
                expires_at=int(expiry.timestamp()) if expiry else None,
                resource=self.flask_app.config["MCP_PUBLIC_URL"],
            )


def create_mcp_server(flask_app=None) -> FastMCP:
    app = flask_app or create_app("production")
    public_url = app.config["MCP_PUBLIC_URL"].rstrip("/")
    parsed = urlsplit(public_url)
    issuer = f"{parsed.scheme}://{parsed.netloc}"
    server = FastMCP(
        "mCorsi",
        instructions=(
            "Assistente degli operatori mCorsi. Usa i dati personali solo per il compito "
            "richiesto. Gli strumenti non restituiscono file o contenuti degli attestati."
        ),
        token_verifier=DatabaseTokenVerifier(app),
        auth=AuthSettings(issuer_url=issuer, resource_server_url=None, required_scopes=[]),
        host=app.config["MCP_HOST"],
        port=app.config["MCP_PORT"],
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_csv(app.config["MCP_ALLOWED_HOSTS"]),
            allowed_origins=_csv(app.config["MCP_ALLOWED_ORIGINS"]),
        ),
    )

    def in_app_context(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with app.app_context():
                return function(*args, **kwargs)

        return wrapped

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    )
    @in_app_context
    def list_courses(status: str | None = None, upcoming_only: bool = False, limit: int = 25) -> dict:
        """Elenca corsi, date, referenti e conteggi; status può essere omesso."""
        access = require_scope("courses:read")
        result = list_courses_data(status=status, upcoming_only=upcoming_only, limit=limit)
        record_tool_call(access, "list_courses", {"status": status, "result_count": result["count"]})
        return result

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    )
    @in_app_context
    def get_course(course_code: str) -> dict:
        """Restituisce i dettagli operativi di un corso identificato dal codice."""
        access = require_scope("courses:read")
        result = get_course_data(course_code)
        record_tool_call(access, "get_course", {"course_code": result["code"]})
        return result

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    )
    @in_app_context
    def list_pending_admissions(course_code: str | None = None, limit: int = 50) -> dict:
        """Elenca le richieste di ammissione ancora da decidere."""
        access = require_scope("admissions:read")
        result = pending_admissions_data(course_code=course_code, limit=limit)
        record_tool_call(access, "list_pending_admissions", {"result_count": result["count"]})
        return result

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    )
    @in_app_context
    def get_participant_training(email: str) -> dict:
        """Mostra corsi e attestati di un partecipante cercato per email."""
        access = require_scope("participants:read")
        require_scope("certificates:read")
        result = participant_training_data(email)
        record_tool_call(access, "get_participant_training", {"participant_email": result["participant"]["email"]})
        return result

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    )
    @in_app_context
    def list_expiring_certificates(days: int = 180, limit: int = 100) -> dict:
        """Elenca gli attestati verificati che scadranno nell'intervallo indicato."""
        access = require_scope("certificates:read")
        result = expiring_certificates_data(days=days, limit=limit)
        record_tool_call(access, "list_expiring_certificates", {"days": days, "result_count": result["count"]})
        return result

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    )
    @in_app_context
    def get_notification_status() -> dict:
        """Restituisce conteggi e prossimi elementi della coda email."""
        access = require_scope("notifications:read")
        result = notification_status_data()
        record_tool_call(access, "get_notification_status", {"counts": result["counts"]})
        return result

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
    )
    @in_app_context
    def enqueue_due_reminders() -> dict:
        """Accoda i promemoria dovuti senza inviare email; l'operazione è idempotente."""
        access = require_scope("automation:write")
        return enqueue_reminders_data(access)

    return server


def run() -> None:
    create_mcp_server().run(transport="streamable-http")
