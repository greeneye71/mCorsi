from __future__ import annotations


# Questo è il messaggio della policy, non una credenziale incorporata.
PASSWORD_POLICY_MESSAGE = (  # nosec B105
    "La password deve avere da 12 a 128 caratteri, contenere maiuscole, "
    "minuscole, numeri e caratteri speciali e non essere una password comune."
)

COMMON_PASSWORDS = {
    "password123!",
    "password1234!",
    "qwerty123456!",
    "amministratore1!",
    "administrator1!",
    "cambiami1234!",
}


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 12 or len(password) > 128:
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
    if password.casefold() in COMMON_PASSWORDS:
        errors.append("password comune")
    return errors


def password_is_valid(password: str) -> bool:
    return not password_policy_errors(password)
