from __future__ import annotations

import asyncio
import re

from starlette.testclient import TestClient

from mcorsi.extensions import db
from mcorsi.mcp_server import DatabaseTokenVerifier, create_mcp_server
from mcorsi.models import McpAccessToken, Role, User
from mcorsi.services.mcp_access import verify_access_token


def _admin() -> User:
    user = User(email="admin-mcp@example.it", profile_completed=True)
    user.roles.extend(
        [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_mcp_token_lifecycle_and_verifier(app, runner):
    with app.app_context():
        _admin()

    created = runner.invoke(
        args=[
            "mcp",
            "token-create",
            "--name",
            "Claude operatori",
            "--creator-email",
            "admin-mcp@example.it",
            "--scope",
            "courses:read",
            "--scope",
            "certificates:read",
            "--days",
            "30",
        ]
    )
    assert created.exit_code == 0, created.output
    raw_token = re.search(r"mcorsi_[A-Za-z0-9]+_[A-Za-z0-9_-]+", created.output).group(0)

    with app.app_context():
        access = verify_access_token(raw_token, update_last_used=False)
        assert access is not None
        assert access.scopes == ["certificates:read", "courses:read"]
        assert verify_access_token("mcorsi_nonvalido_token", update_last_used=False) is None
        verified = asyncio.run(DatabaseTokenVerifier(app).verify_token(raw_token))
        assert verified is not None
        assert verified.client_id == access.id

    listed = runner.invoke(args=["mcp", "token-list"])
    assert listed.exit_code == 0
    assert "Claude operatori" in listed.output

    with app.app_context():
        prefix = McpAccessToken.query.one().token_prefix
    revoked = runner.invoke(args=["mcp", "token-revoke", prefix])
    assert revoked.exit_code == 0
    with app.app_context():
        assert verify_access_token(raw_token, update_last_used=False) is None


def test_mcp_endpoint_requires_bearer_and_publishes_scoped_tools(app, runner):
    with app.app_context():
        _admin()
    created = runner.invoke(
        args=[
            "mcp",
            "token-create",
            "--name",
            "Test connector",
            "--creator-email",
            "admin-mcp@example.it",
            "--scope",
            "courses:read",
        ]
    )
    raw_token = re.search(r"mcorsi_[A-Za-z0-9]+_[A-Za-z0-9_-]+", created.output).group(0)
    app.config.update(MCP_ALLOWED_HOSTS="testserver", MCP_ALLOWED_ORIGINS="https://client.test")
    server = create_mcp_server(app)
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "list_courses",
        "get_course",
        "list_pending_admissions",
        "get_participant_training",
        "list_expiring_certificates",
        "get_notification_status",
        "enqueue_due_reminders",
    }
    assert by_name["list_courses"].annotations.readOnlyHint is True
    assert by_name["enqueue_due_reminders"].annotations.readOnlyHint is False

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(server.streamable_http_app()) as client:
        unauthorized = client.post("/mcp", json=payload, headers=headers)
        assert unauthorized.status_code == 401
        authorized = client.post(
            "/mcp", json=payload, headers={**headers, "Authorization": f"Bearer {raw_token}"}
        )
        assert authorized.status_code == 200
        assert authorized.json()["result"]["serverInfo"]["name"] == "mCorsi"
