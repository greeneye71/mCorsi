from __future__ import annotations

import uuid
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user

from ..extensions import db
from ..models import AdmissionRequest, Certificate, Company, Course, ParticipantProfile
from ..services.audit import record_event
from ..services.courses import CourseOperationError, request_admission
from ..services.mail import MailConfigurationError, MailDeliveryError
from ..services.otp import OtpError, OtpRateLimitError, request_participant_code, verify_participant_code
from ..services.participants import normalize_identifier, set_current_company
from ..services.permissions import participant_required
from ..services.questionnaires import has_passed, submitted_attempts
from ..services.secrets import SecretDecryptionError
from .forms import CourseCodeForm, OtpRequestForm, OtpVerifyForm, ParticipantProfileForm


portal_bp = Blueprint("portal", __name__, url_prefix="/participant")


def _masked_email(value: str) -> str:
    local, _, domain = value.partition("@")
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


@portal_bp.route("/access", methods=["GET", "POST"])
def access():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = OtpRequestForm()
    if form.validate_on_submit():
        try:
            challenge = request_participant_code(form.email.data, request.remote_addr or "")
            session["otp_challenge_id"] = challenge.id if challenge else str(uuid.uuid4())
            session["otp_email_masked"] = _masked_email(form.email.data.strip().casefold())
            flash("Se l'indirizzo è abilitato, riceverai a breve un codice temporaneo.", "success")
            return redirect(url_for("portal.verify"))
        except OtpRateLimitError as exc:
            flash(str(exc), "error")
        except (MailConfigurationError, MailDeliveryError, SecretDecryptionError):
            flash("Il servizio email non è disponibile. Riprova più tardi.", "error")
    return render_template("portal/access.html", form=form)


@portal_bp.route("/verify", methods=["GET", "POST"])
def verify():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    challenge_id = session.get("otp_challenge_id")
    if not challenge_id:
        return redirect(url_for("portal.access"))
    form = OtpVerifyForm()
    if form.validate_on_submit():
        try:
            user = verify_participant_code(challenge_id, form.code.data)
            session.clear()
            login_user(user)
            flash("Accesso effettuato.", "success")
            if not user.profile_completed:
                return redirect(url_for("portal.profile"))
            return redirect(url_for("portal.dashboard"))
        except OtpError as exc:
            flash(str(exc), "error")
    return render_template(
        "portal/verify.html", form=form, masked_email=session.get("otp_email_masked", "")
    )


def _fill_company_form(form: ParticipantProfileForm, company: Company | None) -> None:
    if company is None:
        return
    form.vat_number.data = company.vat_number
    form.company_business_name.data = company.business_name
    form.company_tax_code.data = company.tax_code
    form.company_address.data = company.address
    form.company_postal_code.data = company.postal_code
    form.company_city.data = company.city
    form.company_province.data = company.province
    form.company_country.data = company.country
    form.company_email.data = company.email
    form.company_pec.data = company.pec


def _new_company_valid(form: ParticipantProfileForm) -> bool:
    required = [
        (form.company_business_name, "Indica la ragione sociale."),
        (form.company_address, "Indica l'indirizzo."),
        (form.company_postal_code, "Indica il CAP."),
        (form.company_city, "Indica il comune."),
        (form.company_email, "Indica l'email aziendale."),
    ]
    valid = True
    for field, message in required:
        if not (field.data or "").strip():
            field.errors.append(message)
            valid = False
    return valid


@portal_bp.route("/profile", methods=["GET", "POST"])
@participant_required
def profile():
    profile = current_user.participant_profile
    form = ParticipantProfileForm(obj=current_user)
    current_company = None
    if profile and profile.current_employment:
        current_company = profile.current_employment.company
    if not form.is_submitted():
        if profile:
            form.birth_place.data = profile.birth_place
            form.birth_date.data = profile.birth_date
            form.tax_code.data = profile.tax_code
            form.certificate_title.data = profile.certificate_title
        _fill_company_form(form, current_company)

    if form.validate_on_submit():
        company = None
        vat_number = normalize_identifier(form.vat_number.data or "")
        if vat_number:
            company = Company.query.filter_by(vat_number=vat_number).first()
            if company is None:
                if not _new_company_valid(form):
                    return render_template("portal/profile.html", form=form, is_first_access=not current_user.profile_completed)
                company = Company(
                    business_name=form.company_business_name.data.strip(),
                    vat_number=vat_number,
                    tax_code=normalize_identifier(form.company_tax_code.data or ""),
                    address=form.company_address.data.strip(),
                    postal_code=form.company_postal_code.data.strip(),
                    city=form.company_city.data.strip(),
                    province=(form.company_province.data or "").strip().upper(),
                    country=(form.company_country.data or "IT").strip().upper(),
                    email=form.company_email.data.strip().casefold(),
                    pec=(form.company_pec.data or "").strip().casefold(),
                    verification_status="pending",
                    source="participant",
                )
                db.session.add(company)
                db.session.flush()

        current_user.first_name = form.first_name.data.strip()
        current_user.last_name = form.last_name.data.strip()
        current_user.mobile_phone = (form.mobile_phone.data or "").strip()
        if current_user.participant_profile is None:
            current_user.participant_profile = ParticipantProfile()
            db.session.add(current_user.participant_profile)
        profile = current_user.participant_profile
        profile.birth_place = form.birth_place.data.strip()
        profile.birth_date = form.birth_date.data
        profile.tax_code = normalize_identifier(form.tax_code.data or "")
        profile.certificate_title = (form.certificate_title.data or "").strip()
        set_current_company(profile, company.id if company else "")
        current_user.profile_completed = True
        record_event(
            "participant.profile_completed",
            actor=current_user,
            target_type="user",
            target_id=current_user.id,
            detail={"company_id": company.id if company else None},
        )
        db.session.commit()
        flash("Profilo salvato.", "success")
        return redirect(url_for("portal.dashboard"))
    return render_template(
        "portal/profile.html", form=form, is_first_access=not current_user.profile_completed
    )


@portal_bp.get("")
@participant_required
def dashboard():
    if not current_user.profile_completed:
        return redirect(url_for("portal.profile"))
    admissions = (
        AdmissionRequest.query.filter_by(participant_user_id=current_user.id)
        .order_by(AdmissionRequest.created_at.desc())
        .all()
    )
    questionnaire_states = {}
    for admission in admissions:
        for questionnaire in admission.course.questionnaires:
            if not questionnaire.is_published:
                continue
            attempts = submitted_attempts(questionnaire, current_user)
            questionnaire_states[questionnaire.id] = {
                "attempts": attempts,
                "passed": has_passed(questionnaire, current_user),
                "remaining": max(0, questionnaire.max_attempts - len(attempts)),
            }
    certificates = Certificate.query.filter_by(participant_user_id=current_user.id).order_by(Certificate.course_date.desc()).all()
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
        "portal/dashboard.html",
        admissions=admissions,
        questionnaire_states=questionnaire_states,
        course_code_form=CourseCodeForm(),
        certificates=certificates,
        expiry_states=expiry_states,
    )


@portal_bp.post("/admissions")
@participant_required
def add_admission():
    if not current_user.profile_completed:
        return redirect(url_for("portal.profile"))
    form = CourseCodeForm()
    if form.validate_on_submit():
        code = normalize_identifier(form.code.data)
        course = Course.query.filter_by(code=code).first()
        if course is None or course.status != "open":
            flash("Codice non valido o corso non aperto alle richieste.", "error")
        else:
            try:
                request_admission(course, current_user)
                db.session.commit()
                flash("Richiesta inviata al referente del corso.", "success")
            except CourseOperationError as exc:
                db.session.rollback()
                flash(str(exc), "error")
    else:
        flash("Controlla il codice del corso.", "error")
    return redirect(url_for("portal.dashboard"))
