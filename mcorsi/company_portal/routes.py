from __future__ import annotations

import uuid
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user

from ..extensions import db
from ..models import Certificate, Company
from ..services.mail import MailConfigurationError, MailDeliveryError
from ..services.otp import OtpError, OtpRateLimitError, request_company_code, verify_company_code
from ..services.permissions import company_required
from ..services.secrets import SecretDecryptionError
from .forms import CompanyAccessForm, CompanyVerifyForm


company_portal_bp = Blueprint("company_portal", __name__, url_prefix="/company")


def _masked_email(value: str) -> str:
    local, _, domain = value.partition("@")
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


@company_portal_bp.route("/access", methods=["GET", "POST"])
def access():
    if current_user.is_authenticated and session.get("company_id"):
        return redirect(url_for("company_portal.dashboard"))
    form = CompanyAccessForm()
    if form.validate_on_submit():
        try:
            challenge = request_company_code(
                form.email.data, form.vat_number.data, request.remote_addr or ""
            )
            session["company_otp_challenge_id"] = challenge.id if challenge else str(uuid.uuid4())
            session["company_otp_email_masked"] = _masked_email(form.email.data.strip().casefold())
            flash("Se i dati sono abilitati, riceverai a breve un codice temporaneo.", "success")
            return redirect(url_for("company_portal.verify"))
        except OtpRateLimitError as exc:
            flash(str(exc), "error")
        except (MailConfigurationError, MailDeliveryError, SecretDecryptionError):
            flash("Il servizio email non è disponibile. Riprova più tardi.", "error")
    return render_template("company_portal/access.html", form=form)


@company_portal_bp.route("/verify", methods=["GET", "POST"])
def verify():
    challenge_id = session.get("company_otp_challenge_id")
    if not challenge_id:
        return redirect(url_for("company_portal.access"))
    form = CompanyVerifyForm()
    if form.validate_on_submit():
        try:
            user, company = verify_company_code(challenge_id, form.code.data)
            session.clear()
            login_user(user)
            session["company_id"] = company.id
            flash("Accesso azienda effettuato.", "success")
            return redirect(url_for("company_portal.dashboard"))
        except OtpError as exc:
            flash(str(exc), "error")
    return render_template(
        "company_portal/verify.html",
        form=form,
        masked_email=session.get("company_otp_email_masked", ""),
    )


@company_portal_bp.get("")
@company_required
def dashboard():
    company = db.get_or_404(Company, session["company_id"])
    certificates = (
        Certificate.query.filter_by(
            company_id=company.id, verification_status="verified", status="valid"
        )
        .order_by(Certificate.course_date.desc())
        .all()
    )
    today = date.today()
    expiry_states = {}
    for certificate in certificates:
        if certificate.expires_at is None:
            expiry_states[certificate.id] = "none"
        elif certificate.expires_at < today:
            expiry_states[certificate.id] = "expired"
        elif certificate.expires_at <= today + timedelta(days=180):
            expiry_states[certificate.id] = "expiring"
        else:
            expiry_states[certificate.id] = "valid"
    return render_template(
        "company_portal/dashboard.html",
        company=company,
        certificates=certificates,
        expiry_states=expiry_states,
    )
