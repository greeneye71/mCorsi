from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from ..cli import ensure_roles
from ..extensions import db
from ..models import Certificate, Company, Employment, ParticipantProfile, User, normalize_email
from ..services.audit import record_event
from ..services.participants import (
    EmploymentVerificationError,
    approve_company_association,
    is_valid_italian_vat_number,
    normalize_identifier,
    normalize_vat_number,
    reject_company_association,
    set_current_company,
    vat_number_variants,
)
from ..services.permissions import staff_required
from .forms import CompanyForm, EmploymentDecisionForm, ParticipantForm


participants_bp = Blueprint("participants", __name__, url_prefix="/participants")
companies_bp = Blueprint("companies", __name__, url_prefix="/companies")


def _company_choices():
    companies = Company.query.order_by(Company.business_name).all()
    return [("", "Nessuna azienda")] + [
        (company.id, f"{company.business_name} · {company.vat_number}") for company in companies
    ]


def _current_company_id(user: User) -> str:
    profile = user.participant_profile
    employment = profile.current_employment if profile else None
    return employment.company_id if employment else ""


def _apply_company(form: CompanyForm, company: Company) -> None:
    company.business_name = form.business_name.data.strip()
    company.vat_number = normalize_vat_number(form.vat_number.data)
    company.tax_code = normalize_identifier(form.tax_code.data or "")
    company.address = form.address.data.strip()
    company.postal_code = form.postal_code.data.strip()
    company.city = form.city.data.strip()
    company.province = (form.province.data or "").strip().upper()
    company.country = form.country.data.strip().upper()
    company.email = normalize_email(form.email.data)
    company.pec = normalize_email(form.pec.data) if form.pec.data else ""
    company.verification_status = form.verification_status.data


def _apply_participant(form: ParticipantForm, user: User) -> None:
    user.email = normalize_email(form.email.data)
    user.first_name = form.first_name.data.strip()
    user.last_name = form.last_name.data.strip()
    user.mobile_phone = (form.mobile_phone.data or "").strip()
    if user.participant_profile is None:
        user.participant_profile = ParticipantProfile()
        db.session.add(user.participant_profile)
    profile = user.participant_profile
    profile.birth_place = (form.birth_place.data or "").strip()
    profile.birth_date = form.birth_date.data
    profile.tax_code = normalize_identifier(form.tax_code.data or "")
    profile.certificate_title = (form.certificate_title.data or "").strip()
    user.profile_completed = bool(
        user.first_name and user.last_name and profile.birth_place and profile.birth_date
    )
    set_current_company(profile, form.company_id.data or "", actor=current_user)


def _verified_company_selected(form: ParticipantForm) -> bool:
    company_id = form.company_id.data or ""
    if not company_id:
        return True
    company = db.session.get(Company, company_id)
    if company is not None and company.verification_status == "verified":
        return True
    form.company_id.errors.append("Seleziona un'azienda verificata.")
    return False


def _valid_company_vat(form: CompanyForm) -> bool:
    if (form.country.data or "").strip().upper() != "IT":
        return True
    if is_valid_italian_vat_number(form.vat_number.data):
        return True
    form.vat_number.errors.append("La partita IVA italiana non è valida.")
    return False


@participants_bp.get("")
@staff_required
def index():
    users = (
        User.query.filter(User.roles.any(name="participant"))
        .order_by(User.last_name, User.first_name, User.email)
        .all()
    )
    return render_template("participants/index.html", participants=users)


@participants_bp.route("/new", methods=["GET", "POST"])
@staff_required
def create():
    form = ParticipantForm()
    form.company_id.choices = _company_choices()
    if form.validate_on_submit() and _verified_company_selected(form):
        email = normalize_email(form.email.data)
        if User.query.filter_by(email=email).first():
            form.email.errors.append("Esiste già un utente con questa email.")
        else:
            roles = ensure_roles()
            user = User(email=email, is_active=True)
            user.roles.append(roles["participant"])
            _apply_participant(form, user)
            db.session.add(user)
            record_event(
                "participant.created",
                actor=current_user,
                target_type="user",
                target_id=user.id,
                detail={"email": user.email},
            )
            db.session.commit()
            flash("Partecipante creato.", "success")
            return redirect(url_for("participants.index"))
    return render_template("participants/form.html", form=form, heading="Nuovo partecipante")


@participants_bp.route("/<user_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(user_id: str):
    user = db.get_or_404(User, user_id)
    if not user.has_role("participant"):
        return redirect(url_for("participants.index"))
    profile = user.participant_profile or ParticipantProfile()
    form = ParticipantForm(obj=user)
    form.company_id.choices = _company_choices()
    if not form.is_submitted():
        form.birth_place.data = profile.birth_place
        form.birth_date.data = profile.birth_date
        form.tax_code.data = profile.tax_code
        form.certificate_title.data = profile.certificate_title
        form.company_id.data = _current_company_id(user)
    if form.validate_on_submit() and _verified_company_selected(form):
        email = normalize_email(form.email.data)
        duplicate = User.query.filter(User.email == email, User.id != user.id).first()
        if duplicate:
            form.email.errors.append("Esiste già un utente con questa email.")
        else:
            _apply_participant(form, user)
            record_event(
                "participant.updated",
                actor=current_user,
                target_type="user",
                target_id=user.id,
            )
            db.session.commit()
            flash("Partecipante aggiornato.", "success")
            return redirect(url_for("participants.index"))
    return render_template(
        "participants/form.html", form=form, heading="Modifica partecipante", participant=user,
        certificates=Certificate.query.filter_by(participant_user_id=user.id).order_by(Certificate.course_date.desc()).all(),
    )


@companies_bp.get("")
@staff_required
def index():
    companies = Company.query.order_by(Company.business_name).all()
    pending_employments = (
        Employment.query.filter_by(verification_status="pending")
        .order_by(Employment.created_at)
        .all()
    )
    return render_template(
        "companies/index.html",
        companies=companies,
        pending_employments=pending_employments,
        employment_form=EmploymentDecisionForm(),
    )


def _decide_employment(employment_id: str, *, approve: bool):
    employment = db.get_or_404(Employment, employment_id)
    form = EmploymentDecisionForm()
    if not form.validate_on_submit():
        flash("Richiesta di associazione non valida.", "error")
        return redirect(url_for("companies.index"))
    try:
        if approve:
            approve_company_association(employment, actor=current_user)
        else:
            reject_company_association(employment, actor=current_user)
        record_event(
            "employment.association_approved" if approve else "employment.association_rejected",
            actor=current_user,
            target_type="employment",
            target_id=employment.id,
            detail={
                "participant_user_id": employment.participant_user_id,
                "company_id": employment.company_id,
            },
        )
        db.session.commit()
        flash("Associazione approvata." if approve else "Associazione rifiutata.", "success")
    except EmploymentVerificationError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("companies.index"))


@companies_bp.post("/associations/<employment_id>/approve")
@staff_required
def approve_employment(employment_id: str):
    return _decide_employment(employment_id, approve=True)


@companies_bp.post("/associations/<employment_id>/reject")
@staff_required
def reject_employment(employment_id: str):
    return _decide_employment(employment_id, approve=False)


@companies_bp.route("/new", methods=["GET", "POST"])
@staff_required
def create():
    form = CompanyForm()
    if form.validate_on_submit() and _valid_company_vat(form):
        vat_number = normalize_vat_number(form.vat_number.data)
        if Company.query.filter(Company.vat_number.in_(vat_number_variants(vat_number))).first():
            form.vat_number.errors.append("Esiste già un'azienda con questa partita IVA.")
        else:
            company = Company(source="operator")
            _apply_company(form, company)
            db.session.add(company)
            db.session.flush()
            record_event(
                "company.created",
                actor=current_user,
                target_type="company",
                target_id=company.id,
                detail={
                    "vat_number": company.vat_number,
                    "verification_status": company.verification_status,
                },
            )
            db.session.commit()
            flash("Azienda creata.", "success")
            return redirect(url_for("companies.index"))
    return render_template("companies/form.html", form=form, heading="Nuova azienda")


@companies_bp.route("/<company_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(company_id: str):
    company = db.get_or_404(Company, company_id)
    form = CompanyForm(obj=company)
    if form.validate_on_submit() and _valid_company_vat(form):
        vat_number = normalize_vat_number(form.vat_number.data)
        duplicate = Company.query.filter(
            Company.vat_number.in_(vat_number_variants(vat_number)),
            Company.id != company.id,
        ).first()
        if duplicate:
            form.vat_number.errors.append("Esiste già un'azienda con questa partita IVA.")
        else:
            previous_verification_status = company.verification_status
            _apply_company(form, company)
            record_event(
                "company.updated",
                actor=current_user,
                target_type="company",
                target_id=company.id,
            )
            if company.verification_status != previous_verification_status:
                record_event(
                    "company.verification_status_changed",
                    actor=current_user,
                    target_type="company",
                    target_id=company.id,
                    detail={
                        "from": previous_verification_status,
                        "to": company.verification_status,
                    },
                )
            db.session.commit()
            flash("Azienda aggiornata.", "success")
            return redirect(url_for("companies.index"))
    return render_template("companies/form.html", form=form, heading="Modifica azienda", company=company)
