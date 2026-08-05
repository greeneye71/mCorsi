from mcorsi.extensions import db
from mcorsi.models import User


def test_admin_lifecycle(app, runner):
    result = runner.invoke(
        args=["admin", "create", "--email", "admin@example.it"],
        input="PasswordMoltoSicura!\nPasswordMoltoSicura!\n",
    )
    assert result.exit_code == 0, result.output

    with app.app_context():
        user = User.query.filter_by(email="admin@example.it").one()
        assert user.has_role("admin", "operator")
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
        args=["admin", "create", "--email", "operator@example.it"],
        input=(
            "troppocorta\n"
            "troppocorta\n"
            "PasswordValida123!\n"
            "PasswordValida123!\n"
        ),
    )
    assert result.exit_code == 0, result.output
    assert "almeno 12 caratteri" in result.output
