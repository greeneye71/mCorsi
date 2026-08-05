from mcorsi.extensions import db
from mcorsi.models import SystemVersion
from mcorsi.version import APP_VERSION, DATABASE_VERSION


def test_version_is_stored_displayed_and_reported(app, client, runner):
    with app.app_context():
        stored = db.session.get(SystemVersion, 1)
        assert stored.application_version == APP_VERSION
        assert stored.database_version == DATABASE_VERSION

    login = client.get("/auth/login")
    assert login.status_code == 200
    assert f"mCorsi v{APP_VERSION}".encode() in login.data

    live = client.get("/health/live").get_json()
    assert live["application_version"] == APP_VERSION
    ready_response = client.get("/health/ready")
    assert ready_response.status_code == 200
    ready = ready_response.get_json()
    assert ready["database_version"] == DATABASE_VERSION
    assert ready["components"]["database_schema"] == "ok"

    command = runner.invoke(args=["version"])
    assert command.exit_code == 0, command.output
    assert f"mCorsi {APP_VERSION}" in command.output
    assert f"Database {DATABASE_VERSION}" in command.output
    assert "Compatibilità: ok" in command.output


def test_readiness_rejects_incompatible_database_version(app, client):
    with app.app_context():
        stored = db.session.get(SystemVersion, 1)
        stored.database_version = DATABASE_VERSION + 1
        db.session.commit()

    response = client.get("/health/ready")
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["components"]["database_schema"] == "incompatible"
