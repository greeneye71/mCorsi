from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..extensions import db
from ..models import Company, CompanyContact, OneTimeCode, Role, User, normalize_email
from .participants import normalize_identifier
from .audit import record_event
from .mail import send_email


PARTICIPANT_LOGIN_PURPOSE = "participant_login"
COMPANY_LOGIN_PURPOSE = "company_login"


class OtpError(ValueError):
    pass


class OtpRateLimitError(OtpError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash_code(challenge_id: str, code: str) -> str:
    pepper = current_app.config["OTP_PEPPER"].encode("utf-8")
    return hmac.new(pepper, f"{challenge_id}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _participant_role() -> Role:
    role = Role.query.filter_by(name="participant").first()
    if role is None:
        role = Role(name="participant")
        db.session.add(role)
        db.session.flush()
    return role


def _company_role() -> Role:
    role = Role.query.filter_by(name="company_contact").first()
    if role is None:
        role = Role(name="company_contact")
        db.session.add(role)
        db.session.flush()
    return role


def request_participant_code(email: str, requested_ip: str = "") -> OneTimeCode | None:
    now = datetime.now(timezone.utc)
    normalized = normalize_email(email)
    user = User.query.filter_by(email=normalized).first()
    if user is not None and not user.is_active:
        return None

    cooldown = now - timedelta(seconds=current_app.config["OTP_RESEND_COOLDOWN_SECONDS"])
    hour_ago = now - timedelta(hours=1)
    if user is not None:
        latest = (
            OneTimeCode.query.filter_by(user_id=user.id, purpose=PARTICIPANT_LOGIN_PURPOSE)
            .order_by(OneTimeCode.created_at.desc())
            .first()
        )
        if latest and _aware(latest.created_at) > cooldown:
            raise OtpRateLimitError("Attendi prima di richiedere un nuovo codice.")
        hourly_count = OneTimeCode.query.filter(
            OneTimeCode.user_id == user.id,
            OneTimeCode.purpose == PARTICIPANT_LOGIN_PURPOSE,
            OneTimeCode.created_at >= hour_ago,
        ).count()
        if hourly_count >= current_app.config["OTP_MAX_PER_HOUR"]:
            raise OtpRateLimitError("Troppe richieste. Riprova più tardi.")
    if requested_ip:
        ip_count = OneTimeCode.query.filter(
            OneTimeCode.requested_ip == requested_ip,
            OneTimeCode.created_at >= hour_ago,
        ).count()
        if ip_count >= current_app.config["OTP_MAX_PER_IP_HOUR"]:
            raise OtpRateLimitError("Troppe richieste. Riprova più tardi.")

    if user is None:
        user = User(email=normalized, profile_completed=False, is_active=True)
        db.session.add(user)
        db.session.flush()

    for previous in OneTimeCode.query.filter_by(
        user_id=user.id, purpose=PARTICIPANT_LOGIN_PURPOSE, consumed_at=None
    ).all():
        previous.consumed_at = now

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OneTimeCode(
        id=str(uuid.uuid4()),
        user=user,
        purpose=PARTICIPANT_LOGIN_PURPOSE,
        expires_at=now + timedelta(minutes=current_app.config["OTP_EXPIRY_MINUTES"]),
        max_attempts=current_app.config["OTP_MAX_ATTEMPTS"],
        requested_ip=requested_ip or "",
    )
    challenge.code_hash = _hash_code(challenge.id, code)
    db.session.add(challenge)
    db.session.commit()

    try:
        send_email(
            recipient=user.email,
            subject="Il tuo codice di accesso a mCorsi",
            text_body=(
                f"Il tuo codice temporaneo è: {code}\n\n"
                f"Scade tra {current_app.config['OTP_EXPIRY_MINUTES']} minuti e può essere usato una sola volta.\n"
                "Se non hai richiesto tu questo codice, ignora il messaggio."
            ),
            html_body=(
                "<p>Il tuo codice temporaneo per mCorsi è:</p>"
                f"<p style=\"font-size:28px;font-weight:bold;letter-spacing:6px\">{code}</p>"
                f"<p>Scade tra {current_app.config['OTP_EXPIRY_MINUTES']} minuti e può essere usato una sola volta.</p>"
            ),
        )
    except Exception:
        challenge.consumed_at = datetime.now(timezone.utc)
        db.session.commit()
        raise

    record_event(
        "auth.otp_sent",
        target_type="user",
        target_id=user.id,
        detail={"purpose": PARTICIPANT_LOGIN_PURPOSE},
    )
    db.session.commit()
    return challenge


def verify_participant_code(challenge_id: str, code: str) -> User:
    now = datetime.now(timezone.utc)
    challenge = db.session.get(OneTimeCode, challenge_id)
    if challenge is None or challenge.purpose != PARTICIPANT_LOGIN_PURPOSE:
        raise OtpError("Codice non valido o scaduto.")
    if challenge.consumed_at is not None or _aware(challenge.expires_at) <= now:
        raise OtpError("Codice non valido o scaduto.")
    if challenge.attempts >= challenge.max_attempts:
        raise OtpError("Numero massimo di tentativi raggiunto.")

    challenge.attempts += 1
    valid = hmac.compare_digest(challenge.code_hash, _hash_code(challenge.id, code))
    if not valid:
        if challenge.attempts >= challenge.max_attempts:
            challenge.consumed_at = now
        record_event(
            "auth.otp_failed",
            target_type="user",
            target_id=challenge.user_id,
            detail={"attempt": challenge.attempts},
        )
        db.session.commit()
        raise OtpError("Codice non valido o scaduto.")

    challenge.consumed_at = now
    user = challenge.user
    if not user.is_active:
        db.session.commit()
        raise OtpError("Codice non valido o scaduto.")
    role = _participant_role()
    if not user.has_role("participant"):
        user.roles.append(role)
    user.last_login_at = now
    record_event("auth.otp_succeeded", actor=user, target_type="user", target_id=user.id)
    db.session.commit()
    return user


def request_company_code(
    email: str, vat_number: str, requested_ip: str = ""
) -> OneTimeCode | None:
    now = datetime.now(timezone.utc)
    normalized = normalize_email(email)
    normalized_vat = normalize_identifier(vat_number)
    vat_variants = {normalized_vat}
    if normalized_vat.startswith("IT"):
        vat_variants.add(normalized_vat[2:])
    elif len(normalized_vat) == 11 and normalized_vat.isdigit():
        vat_variants.add("IT" + normalized_vat)
    company = Company.query.filter(
        Company.vat_number.in_(vat_variants), Company.verification_status == "verified"
    ).first()
    user = User.query.filter_by(email=normalized).first()
    contact = None
    if company and user:
        contact = CompanyContact.query.filter_by(
            company_id=company.id, user_id=user.id, is_active=True
        ).first()
    if company is None or (
        normalize_email(company.email) != normalized and contact is None
    ):
        return None
    if user is not None and not user.is_active:
        return None

    cooldown = now - timedelta(seconds=current_app.config["OTP_RESEND_COOLDOWN_SECONDS"])
    hour_ago = now - timedelta(hours=1)
    if user is not None:
        latest = (
            OneTimeCode.query.filter_by(user_id=user.id, purpose=COMPANY_LOGIN_PURPOSE)
            .order_by(OneTimeCode.created_at.desc())
            .first()
        )
        if latest and _aware(latest.created_at) > cooldown:
            raise OtpRateLimitError("Attendi prima di richiedere un nuovo codice.")
        hourly_count = OneTimeCode.query.filter(
            OneTimeCode.user_id == user.id,
            OneTimeCode.purpose == COMPANY_LOGIN_PURPOSE,
            OneTimeCode.created_at >= hour_ago,
        ).count()
        if hourly_count >= current_app.config["OTP_MAX_PER_HOUR"]:
            raise OtpRateLimitError("Troppe richieste. Riprova più tardi.")
    if requested_ip:
        ip_count = OneTimeCode.query.filter(
            OneTimeCode.requested_ip == requested_ip,
            OneTimeCode.created_at >= hour_ago,
        ).count()
        if ip_count >= current_app.config["OTP_MAX_PER_IP_HOUR"]:
            raise OtpRateLimitError("Troppe richieste. Riprova più tardi.")

    if user is None:
        user = User(email=normalized, profile_completed=True, is_active=True)
        db.session.add(user)
        db.session.flush()
    role = _company_role()
    if not user.has_role("company_contact"):
        user.roles.append(role)
    if contact is None:
        contact = CompanyContact(company=company, user=user)
        db.session.add(contact)

    for previous in OneTimeCode.query.filter_by(
        user_id=user.id, purpose=COMPANY_LOGIN_PURPOSE, consumed_at=None
    ).all():
        previous.consumed_at = now
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OneTimeCode(
        id=str(uuid.uuid4()),
        user=user,
        purpose=COMPANY_LOGIN_PURPOSE,
        expires_at=now + timedelta(minutes=current_app.config["OTP_EXPIRY_MINUTES"]),
        max_attempts=current_app.config["OTP_MAX_ATTEMPTS"],
        requested_ip=requested_ip or "",
        context={"company_id": company.id},
    )
    challenge.code_hash = _hash_code(challenge.id, code)
    db.session.add(challenge)
    db.session.commit()
    try:
        send_email(
            recipient=user.email,
            subject="Codice di accesso azienda a mCorsi",
            text_body=(
                f"Codice temporaneo per {company.business_name}: {code}\n\n"
                f"Scade tra {current_app.config['OTP_EXPIRY_MINUTES']} minuti e può essere usato una sola volta."
            ),
            html_body=(
                f"<p>Codice temporaneo per <strong>{company.business_name}</strong>:</p>"
                f"<p style=\"font-size:28px;font-weight:bold;letter-spacing:6px\">{code}</p>"
                f"<p>Scade tra {current_app.config['OTP_EXPIRY_MINUTES']} minuti.</p>"
            ),
        )
    except Exception:
        challenge.consumed_at = datetime.now(timezone.utc)
        db.session.commit()
        raise
    record_event(
        "auth.company_otp_sent",
        target_type="company",
        target_id=company.id,
        detail={"user_id": user.id},
    )
    db.session.commit()
    return challenge


def verify_company_code(challenge_id: str, code: str) -> tuple[User, Company]:
    now = datetime.now(timezone.utc)
    challenge = db.session.get(OneTimeCode, challenge_id)
    if challenge is None or challenge.purpose != COMPANY_LOGIN_PURPOSE:
        raise OtpError("Codice non valido o scaduto.")
    if challenge.consumed_at is not None or _aware(challenge.expires_at) <= now:
        raise OtpError("Codice non valido o scaduto.")
    if challenge.attempts >= challenge.max_attempts:
        raise OtpError("Numero massimo di tentativi raggiunto.")
    challenge.attempts += 1
    valid = hmac.compare_digest(challenge.code_hash, _hash_code(challenge.id, code))
    if not valid:
        if challenge.attempts >= challenge.max_attempts:
            challenge.consumed_at = now
        db.session.commit()
        raise OtpError("Codice non valido o scaduto.")
    company_id = (challenge.context or {}).get("company_id")
    company = db.session.get(Company, company_id)
    contact = CompanyContact.query.filter_by(
        company_id=company_id, user_id=challenge.user_id, is_active=True
    ).first()
    if (
        company is None
        or company.verification_status != "verified"
        or contact is None
        or not challenge.user.is_active
    ):
        challenge.consumed_at = now
        db.session.commit()
        raise OtpError("Codice non valido o scaduto.")
    challenge.consumed_at = now
    challenge.user.last_login_at = now
    record_event(
        "auth.company_otp_succeeded",
        actor=challenge.user,
        target_type="company",
        target_id=company.id,
    )
    db.session.commit()
    return challenge.user, company
