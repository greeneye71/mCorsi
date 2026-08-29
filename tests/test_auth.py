import re

from mcorsi.extensions import db
from mcorsi.models import Role, User
from mcorsi.version import APP_VERSION, DATABASE_VERSION


def _staff(app, *, email="admin@example.it", password="UnaPasswordSicura1!", role="admin"):
    with app.app_context():
        user = User(email=email, profile_completed=True)
        user.set_password(password)
        user.roles.append(Role.query.filter_by(name=role).one())
        db.session.add(user)
        db.session.commit()


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_is_the_shared_entry_point_for_all_audiences(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Corsi, questionari e attestati in un unico posto" in response.data
    assert b"Partecipanti" in response.data
    assert b"Aziende" in response.data
    assert b"Accedi con password" in response.data
    assert b'href="/participant/access"' in response.data
    assert b'href="/company/access"' in response.data


def test_operator_can_login(app, client):
    _staff(app, role="operator")
    with client.session_transaction() as browser_session:
        browser_session["anonymous_marker"] = "must-be-cleared"
    response = client.post(
        "/auth/login",
        data={"email": "ADMIN@example.it", "password": "UnaPasswordSicura1!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"BENTORNATO" in response.data.upper()
    with client.session_transaction() as browser_session:
        assert "anonymous_marker" not in browser_session


def test_operator_can_login_with_csrf_enabled_from_lan(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    _staff(app)
    base_url = "http://192.0.2.10:5100"
    login_page = client.get("/auth/login", base_url=base_url)
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', login_page.data)
    assert match is not None

    response = client.post(
        "/auth/login",
        base_url=base_url,
        environ_overrides={"REMOTE_ADDR": "192.0.2.20"},
        data={
            "email": "admin@example.it",
            "password": "UnaPasswordSicura1!",
            "csrf_token": match.group(1).decode(),
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_secure_session_cookie_is_marked_for_https_only(app, client):
    app.config.update(WTF_CSRF_ENABLED=True, SESSION_COOKIE_SECURE=True)
    _staff(app)
    base_url = "http://192.0.2.10:5100"
    login_page = client.get("/auth/login", base_url=base_url)
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', login_page.data)
    assert match is not None
    assert "Secure" in login_page.headers["Set-Cookie"]


def test_participant_cannot_use_password_login(app, client):
    _staff(app, role="participant")
    response = client.post(
        "/auth/login",
        data={"email": "admin@example.it", "password": "UnaPasswordSicura1!"},
    )
    assert response.status_code == 401
    assert b"non validi" in response.data


def test_password_login_is_rate_limited_by_ip(app, client):
    _staff(app)
    for _attempt in range(app.config["PASSWORD_MAX_FAILURES"]):
        response = client.post(
            "/auth/login",
            data={"email": "admin@example.it", "password": "sbagliata"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/auth/login",
        data={"email": "admin@example.it", "password": "UnaPasswordSicura1!"},
    )
    assert blocked.status_code == 429
    assert b"Troppi tentativi" in blocked.data


def test_password_login_is_rate_limited_by_account_across_ips(app, client):
    app.config["PASSWORD_MAX_FAILURES"] = 2
    _staff(app)
    for index in range(2):
        response = client.post(
            "/auth/login",
            environ_overrides={"REMOTE_ADDR": f"192.0.2.{index + 1}"},
            data={"email": "admin@example.it", "password": "sbagliata"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/auth/login",
        environ_overrides={"REMOTE_ADDR": "192.0.2.200"},
        data={"email": "admin@example.it", "password": "UnaPasswordSicura1!"},
    )
    assert blocked.status_code == 429


def test_responses_include_security_headers(client):
    response = client.get("/auth/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_admin_manages_staff_accounts_in_web_ui(app, client):
    _staff(app)
    login = client.post(
        "/auth/login",
        data={"email": "admin@example.it", "password": "UnaPasswordSicura1!"},
    )
    assert login.status_code == 302
    configuration = client.get("/settings/")
    assert configuration.status_code == 200
    assert b"Email SMTP" in configuration.data
    assert b'/settings/smtp' in configuration.data
    assert f"v{APP_VERSION}".encode() in configuration.data
    assert f"Database {DATABASE_VERSION}".encode() in configuration.data
    created = client.post(
        "/settings/staff",
        data={
            "name": "Operatore Corsi",
            "email": "operatore@example.it",
            "role": "operator",
            "password": "Abcdefgh1!xy",
            "password_confirm": "Abcdefgh1!xy",
        },
    )
    assert created.status_code == 302
    page = client.get("/settings/staff")
    assert page.status_code == 200
    assert b"operatore@example.it" in page.data
    with app.app_context():
        operator = User.query.filter_by(email="operatore@example.it").one()
        operator_id = operator.id
        assert operator.display_name == "Operatore Corsi"
        assert operator.check_password("Abcdefgh1!xy")

    weak = client.post(
        "/settings/staff",
        data={
            "name": "Account debole",
            "email": "debole@example.it",
            "role": "operator",
            "password": "abcdefgh",
            "password_confirm": "abcdefgh",
        },
    )
    assert weak.status_code == 200
    assert "maiuscole, minuscole, numeri".encode() in weak.data

    renamed = client.post(
        f"/settings/staff/{operator_id}/name",
        data={"name": "Referente Formazione"},
    )
    assert renamed.status_code == 302

    changed = client.post(
        f"/settings/staff/{operator_id}/password",
        data={"password": "Xyzabcde2@yz", "password_confirm": "Xyzabcde2@yz"},
    )
    assert changed.status_code == 302
    disabled = client.post(f"/settings/staff/{operator_id}/state", data={})
    assert disabled.status_code == 302
    with app.app_context():
        db.session.expire_all()
        operator = db.session.get(User, operator_id)
        assert operator.display_name == "Referente Formazione"
        assert operator.check_password("Xyzabcde2@yz")
        assert User.query.filter_by(email="debole@example.it").first() is None
        assert operator.is_active is False
