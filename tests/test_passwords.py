import pytest

from mcorsi.services.passwords import password_is_valid, password_policy_errors


@pytest.mark.parametrize(
    "password,missing_requirement",
    [
        ("Ab1!", "lunghezza"),
        ("abcdef1!", "maiuscola"),
        ("ABCDEF1!", "minuscola"),
        ("Abcdefg!", "numero"),
        ("Abcdefg1", "carattere speciale"),
    ],
)
def test_password_policy_rejects_each_missing_requirement(password, missing_requirement):
    assert password_is_valid(password) is False
    assert missing_requirement in password_policy_errors(password)


def test_password_policy_accepts_eight_complex_characters():
    assert password_is_valid("Abcde1!x") is True
