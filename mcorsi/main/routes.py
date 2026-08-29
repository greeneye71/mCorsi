from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import text

from ..extensions import db
from ..models import AdmissionRequest, Company, Course, SystemVersion, User
from ..services.certificates import converter_status
from ..version import APP_VERSION, DATABASE_VERSION


main_bp = Blueprint("main", __name__)


@main_bp.get("/health/live")
def health_live():
    return jsonify(status="ok")


@main_bp.get("/health/ready")
def health_ready():
    components = {}
    try:
        db.session.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "error"
        db.session.rollback()
    stored_version = None
    if components["database"] == "ok":
        try:
            stored_version = db.session.get(SystemVersion, 1)
            if stored_version is None:
                components["database_schema"] = "migration_required"
            elif stored_version.database_version != DATABASE_VERSION:
                components["database_schema"] = "incompatible"
            else:
                components["database_schema"] = "ok"
        except Exception:
            db.session.rollback()
            components["database_schema"] = "migration_required"
    storage = Path(current_app.config["PRIVATE_STORAGE_PATH"])
    components["storage"] = "ok" if storage.is_dir() else "error"
    converter_ok, converter_detail = converter_status()
    components["pdf_converter"] = "ok" if converter_ok else converter_detail
    ready = (
        components["database"] == "ok"
        and components.get("database_schema") == "ok"
        and components["storage"] == "ok"
    )
    payload = {"status": "ok" if ready and converter_ok else "degraded"}
    if current_user.is_authenticated and current_user.has_role("admin", "operator"):
        payload.update(
            application_version=APP_VERSION,
            required_database_version=DATABASE_VERSION,
            database_version=stored_version.database_version if stored_version else None,
            components=components,
        )
    return jsonify(payload), (200 if ready else 503)


@main_bp.get("/")
@login_required
def dashboard():
    if not current_user.has_role("admin", "operator"):
        if current_user.has_role("company_contact"):
            return redirect(url_for("company_portal.dashboard"))
        if current_user.has_role("participant"):
            return redirect(url_for("portal.dashboard"))
        abort(403)
    counts = {
        "courses": Course.query.count(),
        "participants": User.query.filter(User.roles.any(name="participant")).count(),
        "pending_admissions": AdmissionRequest.query.filter_by(status="pending").count(),
        "companies_pending": Company.query.filter_by(verification_status="pending").count(),
    }
    recent_courses = Course.query.order_by(Course.created_at.desc()).limit(5).all()
    return render_template("main/dashboard.html", counts=counts, recent_courses=recent_courses)
