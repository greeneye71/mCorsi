from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, send_file, session, url_for
from pathlib import Path
from flask_login import current_user, login_required

from ..extensions import db
from ..models import (
    Certificate,
    CertificateTemplate,
    Course,
    CourseDocument,
    Enrollment,
    SignatureAsset,
    StoredFile,
    Company,
    CompanyContact,
)
from ..services.audit import record_event
from ..services.certificates import (
    CertificateError,
    converter_status,
    generate_certificate,
    inspect_template,
    readiness,
    validate_signature_image,
    validate_pdf,
)
from ..services.permissions import participant_required, staff_required
from ..services.storage import StorageError, path_for, save_upload
from .forms import (
    AttendanceForm,
    CourseCertificateSettingsForm,
    CourseDocumentForm,
    ParticipantCertificateUploadForm,
    SignatureUploadForm,
    TemplateUploadForm,
)


documents_bp = Blueprint("documents", __name__, url_prefix="/documents")


def _safe_download(stored_file: StoredFile):
    path = path_for(stored_file)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype=stored_file.mime_type,
        as_attachment=True,
        download_name=stored_file.original_name,
        conditional=True,
    )


@documents_bp.route("/library", methods=["GET"])
@staff_required
def library():
    return render_template(
        "documents/library.html",
        templates=CertificateTemplate.query.order_by(CertificateTemplate.created_at.desc()).all(),
        signatures=SignatureAsset.query.order_by(SignatureAsset.created_at.desc()).all(),
        template_form=TemplateUploadForm(),
        signature_form=SignatureUploadForm(),
        converter=converter_status(),
    )


@documents_bp.get("/default-template")
@staff_required
def default_template():
    path = Path(__file__).resolve().parents[1] / "assets" / "default_certificate.docx"
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name="modello-attestato-mcorsi.docx")


@documents_bp.post("/templates")
@staff_required
def upload_template():
    form = TemplateUploadForm()
    if form.validate_on_submit():
        try:
            stored = save_upload(
                form.file.data,
                actor=current_user,
                category="templates",
                allowed_extensions={".docx"},
                allowed_mime_types={
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/octet-stream",
                },
            )
            placeholders = inspect_template(path_for(stored))
            template = CertificateTemplate(
                name=form.name.data.strip(),
                stored_file=stored,
                placeholders=placeholders,
                uploaded_by_user_id=current_user.id,
            )
            db.session.add(template)
            db.session.flush()
            record_event("certificate_template.created", actor=current_user, target_type="certificate_template", target_id=template.id)
            db.session.commit()
            flash("Modello attestato caricato e verificato.", "success")
        except (StorageError, CertificateError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
    else:
        flash("Controlla nome e file DOCX.", "error")
    return redirect(url_for("documents.library"))


@documents_bp.post("/signatures")
@staff_required
def upload_signature():
    form = SignatureUploadForm()
    if form.validate_on_submit():
        try:
            stored = save_upload(
                form.file.data,
                actor=current_user,
                category="signatures",
                allowed_extensions={".png", ".jpg", ".jpeg"},
                allowed_mime_types={"image/png", "image/jpeg", "application/octet-stream"},
            )
            validate_signature_image(path_for(stored))
            signature = SignatureAsset(
                name=form.name.data.strip(),
                signer_name=form.signer_name.data.strip(),
                signer_title=(form.signer_title.data or "").strip(),
                stored_file=stored,
                uploaded_by_user_id=current_user.id,
            )
            db.session.add(signature)
            db.session.flush()
            record_event(
                "signature_asset.created",
                actor=current_user,
                target_type="signature_asset",
                target_id=signature.id,
                detail={"signer_name": signature.signer_name},
            )
            db.session.commit()
            flash("Firma archiviata.", "success")
        except (StorageError, CertificateError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
    else:
        flash("Controlla i dati e l'immagine della firma.", "error")
    return redirect(url_for("documents.library"))


@documents_bp.post("/courses/<course_id>/settings")
@staff_required
def course_settings(course_id: str):
    course = db.get_or_404(Course, course_id)
    form = CourseCertificateSettingsForm()
    form.certificate_template_id.choices = [(item.id, item.name) for item in CertificateTemplate.query.filter_by(is_active=True).all()]
    form.signature_asset_id.choices = [("", "Nessuna firma")] + [(item.id, f"{item.name} · {item.signer_name}") for item in SignatureAsset.query.filter_by(is_active=True).all()]
    if form.validate_on_submit():
        course.certificate_template_id = form.certificate_template_id.data
        course.signature_asset_id = form.signature_asset_id.data or None
        record_event(
            "course.certificate_settings_updated",
            actor=current_user,
            target_type="course",
            target_id=course.id,
            detail={
                "certificate_template_id": course.certificate_template_id,
                "signature_asset_id": course.signature_asset_id,
            },
        )
        db.session.commit()
        flash("Configurazione attestato salvata.", "success")
    else:
        flash("Configurazione non valida.", "error")
    return redirect(url_for("courses.detail", course_id=course.id))


@documents_bp.post("/courses/<course_id>/files")
@staff_required
def upload_course_document(course_id: str):
    course = db.get_or_404(Course, course_id)
    form = CourseDocumentForm()
    if form.validate_on_submit():
        try:
            stored = save_upload(form.file.data, actor=current_user, category="course-documents")
            document = CourseDocument(
                course=course,
                stored_file=stored,
                label=(form.label.data or stored.original_name).strip(),
                sort_order=len(course.documents) + 1,
            )
            db.session.add(document)
            db.session.flush()
            record_event(
                "course_document.created",
                actor=current_user,
                target_type="course_document",
                target_id=document.id,
                detail={"course_id": course.id, "filename": stored.original_name},
            )
            db.session.commit()
            flash("Documento del corso caricato.", "success")
        except StorageError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    else:
        flash("Seleziona un file valido.", "error")
    return redirect(url_for("courses.detail", course_id=course.id))


@documents_bp.get("/course-files/<document_id>")
@login_required
def download_course_document(document_id: str):
    document = db.get_or_404(CourseDocument, document_id)
    allowed = current_user.has_role("admin", "operator") or any(
        item.participant_user_id == current_user.id for item in document.course.enrollments
    )
    if not allowed:
        abort(403)
    record_event(
        "course_document.downloaded",
        actor=current_user,
        target_type="course_document",
        target_id=document.id,
    )
    db.session.commit()
    return _safe_download(document.stored_file)


@documents_bp.post("/enrollments/<enrollment_id>/attendance")
@staff_required
def set_attendance(enrollment_id: str):
    enrollment = db.get_or_404(Enrollment, enrollment_id)
    form = AttendanceForm()
    if form.validate_on_submit():
        enrollment.attendance_status = form.attendance_status.data
        record_event(
            "enrollment.attendance_updated",
            actor=current_user,
            target_type="enrollment",
            target_id=enrollment.id,
            detail={"attendance_status": enrollment.attendance_status},
        )
        db.session.commit()
        flash("Presenza aggiornata.", "success")
    return redirect(url_for("courses.detail", course_id=enrollment.course_id))


@documents_bp.post("/enrollments/<enrollment_id>/certificate")
@staff_required
def create_certificate(enrollment_id: str):
    enrollment = db.get_or_404(Enrollment, enrollment_id)
    try:
        certificate = generate_certificate(enrollment, actor=current_user)
        record_event("certificate.generated", actor=current_user, target_type="certificate", target_id=certificate.id)
        db.session.commit()
        flash(f"Attestato {certificate.certificate_number} generato.", "success")
    except CertificateError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("courses.detail", course_id=enrollment.course_id))


@documents_bp.route("/participant/upload", methods=["GET", "POST"])
@participant_required
def participant_upload():
    form = ParticipantCertificateUploadForm()
    if form.validate_on_submit():
        try:
            stored = save_upload(
                form.file.data,
                actor=current_user,
                category="certificates-uploaded",
                allowed_extensions={".pdf"},
                allowed_mime_types={"application/pdf", "application/octet-stream"},
            )
            validate_pdf(path_for(stored))
            certificate = Certificate(
                participant_user_id=current_user.id,
                company_id=(current_user.participant_profile.current_employment.company_id if current_user.participant_profile and current_user.participant_profile.current_employment else None),
                pdf_file=stored,
                title_snapshot=form.title.data.strip(),
                course_date=form.course_date.data,
                expires_at=form.expires_at.data,
                source="participant_upload",
                verification_status="pending",
                status="valid",
                data_snapshot={},
            )
            db.session.add(certificate)
            db.session.flush()
            record_event(
                "certificate.uploaded_by_participant",
                actor=current_user,
                target_type="certificate",
                target_id=certificate.id,
            )
            db.session.commit()
            flash("Attestato caricato. Sarà visibile come verificato dopo il controllo di un operatore.", "success")
            return redirect(url_for("portal.dashboard"))
        except (StorageError, CertificateError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("documents/participant_upload.html", form=form)


@documents_bp.post("/certificates/<certificate_id>/verify")
@staff_required
def verify_certificate(certificate_id: str):
    certificate = db.get_or_404(Certificate, certificate_id)
    certificate.verification_status = "verified"
    record_event(
        "certificate.verified",
        actor=current_user,
        target_type="certificate",
        target_id=certificate.id,
    )
    db.session.commit()
    flash("Attestato verificato.", "success")
    return redirect(url_for("participants.edit", user_id=certificate.participant_user_id))


@documents_bp.get("/certificates/<certificate_id>/download")
@login_required
def download_certificate(certificate_id: str):
    certificate = db.get_or_404(Certificate, certificate_id)
    company_id = session.get("company_id")
    company = db.session.get(Company, company_id) if company_id else None
    active_contact = (
        CompanyContact.query.filter_by(
            company_id=company_id, user_id=current_user.id, is_active=True
        ).first()
        if company_id
        else None
    )
    company_allowed = (
        current_user.has_role("company_contact")
        and company_id == certificate.company_id
        and company is not None
        and company.verification_status == "verified"
        and active_contact is not None
        and certificate.verification_status == "verified"
    )
    if not current_user.has_role("admin", "operator") and certificate.participant_user_id != current_user.id and not company_allowed:
        abort(403)
    record_event(
        "certificate.downloaded",
        actor=current_user,
        target_type="certificate",
        target_id=certificate.id,
        detail={"company_id": company_id if company_allowed else None},
    )
    db.session.commit()
    return _safe_download(certificate.pdf_file)
