from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ..extensions import db
from ..models import AuditLog, User, normalize_email
from ..services.audit import record_event
from .forms import LoginForm


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def is_safe_redirect(target: str) -> bool:
    reference = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in {"http", "https"} and reference.netloc == candidate.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        remote_ip = request.remote_addr or ""
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=current_app.config["PASSWORD_FAILURE_WINDOW_MINUTES"]
        )
        recent_failures = AuditLog.query.filter(
            AuditLog.event_type == "auth.password_failed",
            AuditLog.ip_address == remote_ip,
            AuditLog.created_at >= cutoff,
        ).count()
        if recent_failures >= current_app.config["PASSWORD_MAX_FAILURES"]:
            record_event("auth.password_rate_limited")
            db.session.commit()
            flash("Troppi tentativi. Attendi alcuni minuti e riprova.", "error")
            return render_template("auth/login.html", form=form), 429
        user = User.query.filter_by(email=normalize_email(form.email.data)).first()
        valid = (
            user is not None
            and user.is_active
            and user.has_role("admin", "operator")
            and user.check_password(form.password.data)
        )
        if not valid:
            record_event("auth.password_failed", detail={"email": normalize_email(form.email.data)})
            db.session.commit()
            flash("Email o password non validi.", "error")
            return render_template("auth/login.html", form=form), 401

        login_user(user, remember=form.remember.data)
        user.last_login_at = datetime.now(timezone.utc)
        record_event("auth.password_succeeded", actor=user, target_type="user", target_id=user.id)
        db.session.commit()
        next_url = request.args.get("next", "")
        if next_url and is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    company_session = bool(session.get("company_id"))
    participant_only = current_user.is_authenticated and current_user.has_role("participant") and not current_user.has_role("admin", "operator")
    if current_user.is_authenticated:
        record_event("auth.logout", actor=current_user, target_type="user", target_id=current_user.id)
        db.session.commit()
    logout_user()
    session.pop("company_id", None)
    flash("Sessione terminata.", "success")
    destination = "company_portal.access" if company_session else ("portal.access" if participant_only else "auth.login")
    return redirect(url_for(destination))
