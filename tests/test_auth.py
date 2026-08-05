from mcorsi.extensions import db
from mcorsi.models import Role, User


def _staff(app, *, email="admin@example.it", password="UnaPasswordSicura!", role="admin"):
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


def test_operator_can_login(app, client):
    _staff(app, role="operator")
    response = client.post(
        "/auth/login",
        data={"email": "ADMIN@example.it", "password": "UnaPasswordSicura!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"BENTORNATO" in response.data.upper()


def test_participant_cannot_use_password_login(app, client):
    _staff(app, role="participant")
    response = client.post(
        "/auth/login",
        data={"email": "admin@example.it", "password": "UnaPasswordSicura!"},
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
        data={"email": "admin@example.it", "password": "UnaPasswordSicura!"},
    )
    assert blocked.status_code == 429
    assert b"Troppi tentativi" in blocked.data


def test_admin_manages_staff_accounts_in_web_ui(app, client):
    _staff(app)
    login = client.post(
        "/auth/login",
        data={"email": "admin@example.it", "password": "UnaPasswordSicura!"},
    )
    assert login.status_code == 302
    created = client.post(
        "/settings/staff",
        data={
            "email": "operatore@example.it",
            "role": "operator",
            "password": "PasswordIniziale!",
            "password_confirm": "PasswordIniziale!",
        },
    )
    assert created.status_code == 302
    page = client.get("/settings/staff")
    assert page.status_code == 200
    assert b"operatore@example.it" in page.data
    with app.app_context():
        operator = User.query.filter_by(email="operatore@example.it").one()
        operator_id = operator.id
        assert operator.check_password("PasswordIniziale!")

    changed = client.post(
        f"/settings/staff/{operator_id}/password",
        data={"password": "PasswordAggiornata!", "password_confirm": "PasswordAggiornata!"},
    )
    assert changed.status_code == 302
    disabled = client.post(f"/settings/staff/{operator_id}/state", data={})
    assert disabled.status_code == 302
    with app.app_context():
        db.session.expire_all()
        operator = db.session.get(User, operator_id)
        assert operator.check_password("PasswordAggiornata!")
        assert operator.is_active is False
