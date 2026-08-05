from mcorsi.extensions import db
from mcorsi.models import User


def test_admin_lifecycle(app, runner):
    result = runner.invoke(
        args=["admin", "create", "--email", "admin@example.it", "--name", "Giovanni"],
        input="PasswordMoltoSicura!\nPasswordMoltoSicura!\n",
    )
    assert result.exit_code == 0, result.output

    with app.app_context():
        user = User.query.filter_by(email="admin@example.it").one()
        assert user.has_role("admin", "operator")
        assert user.display_name == "Giovanni"
        assert user.check_password("PasswordMoltoSicura!")

    changed = runner.invoke(
        args=["admin", "set-password", "admin@example.it"],
        input="PasswordNuovaSicura!\nPasswordNuovaSicura!\n",
    )
    assert changed.exit_code == 0, changed.output

    listed = runner.invoke(args=["admin", "list-users"])
    assert listed.exit_code == 0
    assert "admin@example.it" in listed.output

    disabled = runner.invoke(args=["admin", "disable-user", "admin@example.it"])
    assert disabled.exit_code == 0
    with app.app_context():
        db.session.expire_all()
        assert User.query.filter_by(email="admin@example.it").one().is_active is False


def test_short_password_is_reprompted(runner):
    result = runner.invoke(
        args=["admin", "create", "--email", "operator@example.it", "--name", "Operatore"],
        input=(
            "troppocorta\n"
            "troppocorta\n"
            "PasswordValida123!\n"
            "PasswordValida123!\n"
        ),
    )
    assert result.exit_code == 0, result.output
    assert "almeno 12 caratteri" in result.output


def test_bootstrap_admin_is_idempotent(app, runner):
    first = runner.invoke(
        args=["admin", "bootstrap", "--email", "bootstrap@example.it", "--name", "Amministratore"],
        input="PasswordBootstrap1!\nPasswordBootstrap1!\n",
    )
    assert first.exit_code == 0, first.output
    assert "Amministratore creato" in first.output

    second = runner.invoke(args=["admin", "bootstrap"])
    assert second.exit_code == 0, second.output
    assert "già configurato" in second.output

    with app.app_context():
        admins = User.query.filter(User.roles.any(name="admin")).all()
        assert len(admins) == 1
