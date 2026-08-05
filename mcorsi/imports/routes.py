from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from ..extensions import db
from ..models import ImportBatch
from ..services.audit import record_event
from ..services.imports import HistoricalImportError, confirm_batch, prepare_batch
from ..services.permissions import staff_required
from ..services.storage import StorageError, save_upload
from .forms import ConfirmImportForm, HistoricalImportForm


imports_bp = Blueprint("imports", __name__, url_prefix="/imports")


@imports_bp.route("", methods=["GET", "POST"])
@staff_required
def index():
    form = HistoricalImportForm()
    if form.validate_on_submit():
        try:
            stored = save_upload(
                form.file.data,
                actor=current_user,
                category="imports",
                allowed_extensions={".xlsx"},
                allowed_mime_types={
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/octet-stream",
                },
            )
            batch = ImportBatch(
                stored_file=stored,
                course_title=form.course_title.data.strip(),
                course_date=form.course_date.data,
                created_by_user_id=current_user.id,
            )
            db.session.add(batch)
            prepare_batch(batch)
            db.session.commit()
            return redirect(url_for("imports.preview", batch_id=batch.id))
        except (StorageError, HistoricalImportError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
    batches = ImportBatch.query.order_by(ImportBatch.created_at.desc()).limit(20).all()
    return render_template("imports/index.html", form=form, batches=batches)


@imports_bp.get("/<batch_id>")
@staff_required
def preview(batch_id: str):
    batch = db.get_or_404(ImportBatch, batch_id)
    return render_template("imports/preview.html", batch=batch, confirm_form=ConfirmImportForm())


@imports_bp.post("/<batch_id>/confirm")
@staff_required
def confirm(batch_id: str):
    batch = db.get_or_404(ImportBatch, batch_id)
    form = ConfirmImportForm()
    if form.validate_on_submit():
        try:
            confirm_batch(batch, actor=current_user)
            record_event("historical_import.completed", actor=current_user, target_type="import_batch", target_id=batch.id, detail=batch.summary)
            db.session.commit()
            flash("Storico importato.", "success")
        except HistoricalImportError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return redirect(url_for("imports.preview", batch_id=batch.id))
