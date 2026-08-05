from __future__ import annotations

from functools import wraps

from flask import abort, session
from flask_login import current_user, login_required

from ..extensions import db


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.has_role("admin", "operator"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.has_role("admin"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def participant_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.has_role("participant"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def company_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        from ..models import Company, CompanyContact

        company_id = session.get("company_id")
        contact = CompanyContact.query.filter_by(
            company_id=company_id, user_id=current_user.id, is_active=True
        ).first()
        company = db.session.get(Company, company_id) if company_id else None
        if (
            not current_user.has_role("company_contact")
            or contact is None
            or company is None
            or company.verification_status != "verified"
        ):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def can_review_course(course) -> bool:
    return current_user.has_role("admin") or course.referent_user_id == current_user.id
