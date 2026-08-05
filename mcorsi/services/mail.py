from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app

from ..extensions import db
from ..models import SmtpConfiguration
from .secrets import SecretDecryptionError, decrypt_secret


class MailConfigurationError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    pass


def get_smtp_configuration() -> SmtpConfiguration:
    configuration = db.session.get(SmtpConfiguration, 1)
    if configuration is None:
        raise MailConfigurationError("Configura il servizio SMTP prima di inviare email.")
    return configuration


def send_email(*, recipient: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    if current_app.config.get("MAIL_BACKEND") == "memory":
        current_app.config.setdefault("MAIL_OUTBOX", []).append(
            {
                "recipient": recipient,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
            }
        )
        return

    configuration = get_smtp_configuration()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((configuration.from_name, configuration.from_email))
    message["To"] = recipient
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        password = decrypt_secret(configuration.password_encrypted)
        context = ssl.create_default_context()
        if configuration.use_ssl:
            client_context = smtplib.SMTP_SSL(
                configuration.host,
                configuration.port,
                timeout=configuration.timeout_seconds,
                context=context,
            )
        else:
            client_context = smtplib.SMTP(
                configuration.host,
                configuration.port,
                timeout=configuration.timeout_seconds,
            )
        with client_context as client:
            if configuration.use_starttls and not configuration.use_ssl:
                client.starttls(context=context)
            if configuration.username:
                client.login(configuration.username, password)
            client.send_message(message)
    except SecretDecryptionError:
        raise
    except (OSError, smtplib.SMTPException) as exc:
        raise MailDeliveryError(f"Invio email non riuscito: {exc}") from exc
