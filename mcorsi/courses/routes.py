from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user

from ..extensions import db
from ..models import AdmissionRequest, Course, User, normalize_email
from ..models import CertificateTemplate, SignatureAsset
from ..documents.forms import AttendanceForm, CourseCertificateSettingsForm, CourseDocumentForm
from ..services.certificates import readiness
from ..services.courses import (
    CourseOperationError,
    create_course,
    decide_admission,
    duplicate_course,
    request_admission,
    update_course,
)
from ..services.permissions import can_review_course, staff_required
from .forms import AdmissionAddForm, AdmissionDecisionForm, CourseForm, DuplicateCourseForm


courses_bp = Blueprint("courses", __name__, url_prefix="/courses")


def _staff_choices():
    users = (
        User.query.filter(User.is_active.is_(True))
        .filter(User.roles.any(name="operator"))
        .order_by(User.last_name, User.first_name, User.email)
        .all()
    )
    return [(user.id, user.display_name) for user in users]


def _course_form_data(form: CourseForm) -> dict:
    return {
        "title": form.title.data,
        "description": form.description.data or "",
        "legal_references": form.legal_references.data or "",
        "topics": form.topics.data or "",
        "status": form.status.data,
        "referent_user_id": form.referent_user_id.data,
        "session_date": form.session_date.data,
        "start_time": form.start_time.data,
        "end_time": form.end_time.data,
        "delivery_mode": form.delivery_mode.data,
        "meeting_url": form.meeting_url.data or "",
        "certificate_validity_months": form.certificate_validity_months.data,
    }


@courses_bp.get("")
@staff_required
def index():
    courses = Course.query.order_by(Course.created_at.desc()).all()
    return render_template("courses/index.html", courses=courses)


@courses_bp.route("/new", methods=["GET", "POST"])
@staff_required
def create():
    form = CourseForm()
    form.referent_user_id.choices = _staff_choices()
    if not form.is_submitted():
        form.referent_user_id.data = current_user.id
    if form.validate_on_submit():
        course = create_course(actor=current_user, data=_course_form_data(form))
        db.session.commit()
        flash(f"Corso creato. Codice: {course.code}", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/form.html", form=form, heading="Nuovo corso")


@courses_bp.get("/<course_id>")
@staff_required
def detail(course_id: str):
    course = db.get_or_404(Course, course_id)
    admission_form = AdmissionAddForm()
    decision_form = AdmissionDecisionForm()
    admissions = sorted(course.admission_requests, key=lambda item: item.created_at, reverse=True)
    certificate_settings_form = CourseCertificateSettingsForm()
    certificate_settings_form.certificate_template_id.choices = [
        (item.id, item.name)
        for item in CertificateTemplate.query.filter_by(is_active=True).order_by(CertificateTemplate.name).all()
    ]
    certificate_settings_form.signature_asset_id.choices = [("", "Nessuna firma")] + [
        (item.id, f"{item.name} · {item.signer_name}")
        for item in SignatureAsset.query.filter_by(is_active=True).order_by(SignatureAsset.name).all()
    ]
    certificate_settings_form.certificate_template_id.data = course.certificate_template_id
    certificate_settings_form.signature_asset_id.data = course.signature_asset_id or ""
    enrollment_readiness = {item.id: readiness(item) for item in course.enrollments}
    return render_template(
        "courses/detail.html",
        course=course,
        admissions=admissions,
        admission_form=admission_form,
        decision_form=decision_form,
        may_review=can_review_course(course),
        course_document_form=CourseDocumentForm(),
        certificate_settings_form=certificate_settings_form,
        attendance_form=AttendanceForm(),
        enrollment_readiness=enrollment_readiness,
    )


@courses_bp.route("/<course_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(course_id: str):
    course = db.get_or_404(Course, course_id)
    session = course.first_session
    form = CourseForm(obj=course)
    form.referent_user_id.choices = _staff_choices()
    if not form.is_submitted():
        form.referent_user_id.data = course.referent_user_id
        if session:
            zone = ZoneInfo(course.timezone_name)
            local_start = session.starts_at.replace(tzinfo=timezone.utc).astimezone(zone)
            local_end = session.ends_at.replace(tzinfo=timezone.utc).astimezone(zone)
            form.session_date.data = local_start.date()
            form.start_time.data = local_start.time().replace(tzinfo=None)
            form.end_time.data = local_end.time().replace(tzinfo=None)
    if form.validate_on_submit():
        update_course(course, actor=current_user, data=_course_form_data(form))
        db.session.commit()
        flash("Corso aggiornato.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/form.html", form=form, heading="Modifica corso", course=course)


@courses_bp.route("/<course_id>/duplicate", methods=["GET", "POST"])
@staff_required
def duplicate(course_id: str):
    source = db.get_or_404(Course, course_id)
    form = DuplicateCourseForm()
    form.referent_user_id.choices = _staff_choices()
    if not form.is_submitted():
        form.referent_user_id.data = source.referent_user_id
        if source.first_session:
            zone = ZoneInfo(source.timezone_name)
            start = source.first_session.starts_at.replace(tzinfo=timezone.utc).astimezone(zone)
            end = source.first_session.ends_at.replace(tzinfo=timezone.utc).astimezone(zone)
            form.start_time.data = start.time().replace(tzinfo=None)
            form.end_time.data = end.time().replace(tzinfo=None)
    if form.validate_on_submit():
        course = duplicate_course(
            source,
            actor=current_user,
            referent_user_id=form.referent_user_id.data,
            day=form.session_date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
        )
        db.session.commit()
        flash("Nuova edizione creata in bozza, senza partecipanti.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/duplicate.html", form=form, course=source)


@courses_bp.post("/<course_id>/admissions")
@staff_required
def add_admission(course_id: str):
    course = db.get_or_404(Course, course_id)
    if not can_review_course(course):
        abort(403)
    form = AdmissionAddForm()
    if form.validate_on_submit():
        participant = User.query.filter_by(email=normalize_email(form.email.data)).first()
        if participant is None or not participant.has_role("participant"):
            flash("Partecipante non trovato: crealo prima nell'anagrafica.", "error")
        else:
            try:
                request_admission(course, participant, actor=current_user)
                db.session.commit()
                flash("Richiesta di ammissione registrata.", "success")
            except CourseOperationError as exc:
                db.session.rollback()
                flash(str(exc), "error")
    else:
        flash("Inserisci un indirizzo email valido.", "error")
    return redirect(url_for("courses.detail", course_id=course.id))


def _decide(course_id: str, admission_id: str, approve: bool):
    course = db.get_or_404(Course, course_id)
    if not can_review_course(course):
        abort(403)
    admission = db.get_or_404(AdmissionRequest, admission_id)
    if admission.course_id != course.id:
        abort(404)
    form = AdmissionDecisionForm()
    if not form.validate_on_submit():
        flash("I dati della decisione non sono validi.", "error")
        return redirect(url_for("courses.detail", course_id=course.id))
    try:
        decide_admission(
            admission,
            actor=current_user,
            approve=approve,
            decision_message=form.decision_message.data or "",
            internal_note=form.internal_note.data or "",
        )
        db.session.commit()
        flash("Partecipante ammesso." if approve else "Richiesta rifiutata.", "success")
    except CourseOperationError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("courses.detail", course_id=course.id))


@courses_bp.post("/<course_id>/admissions/<admission_id>/approve")
@staff_required
def approve_admission(course_id: str, admission_id: str):
    return _decide(course_id, admission_id, True)


@courses_bp.post("/<course_id>/admissions/<admission_id>/reject")
@staff_required
def reject_admission(course_id: str, admission_id: str):
    return _decide(course_id, admission_id, False)
