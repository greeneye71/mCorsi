from __future__ import annotations


PASSWORD_POLICY_MESSAGE = (
    "La password deve avere almeno 8 caratteri e contenere maiuscole, "
    "minuscole, numeri e caratteri speciali."
)


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 8:
        errors.append("lunghezza")
    if not any(character.isupper() for character in password):
        errors.append("maiuscola")
    if not any(character.islower() for character in password):
        errors.append("minuscola")
    if not any(character.isdigit() for character in password):
        errors.append("numero")
    if not any(
        not character.isalnum() and not character.isspace() for character in password
    ):
        errors.append("carattere speciale")
    return errors


def password_is_valid(password: str) -> bool:
    return not password_policy_errors(password)
