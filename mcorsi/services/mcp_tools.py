from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mcp.server.auth.middleware.auth_context import get_access_token

from ..extensions import db
from ..models import (
    AdmissionRequest,
    Certificate,
    Course,
    EmailOutbox,
    Enrollment,
    McpAccessToken,
    User,
    normalize_email,
)
from .audit import record_event
from .certificates import course_date
from .notifications import enqueue_reminders


def require_scope(scope: str) -> McpAccessToken:
    principal = get_access_token()
    if principal is None or scope not in principal.scopes:
        raise PermissionError(f"Il token non dispone del permesso {scope}.")
    access = db.session.get(McpAccessToken, principal.client_id)
    if access is None or not access.is_active:
        raise PermissionError("Il token MCP non è più attivo.")
    return access


def record_tool_call(access: McpAccessToken, tool_name: str, detail: dict | None = None) -> None:
    record_event(
        "mcp.tool_called",
        actor=access.created_by,
        target_type="mcp_tool",
        target_id=tool_name,
        detail={"token_prefix": access.token_prefix, **(detail or {})},
    )
    db.session.commit()


def _local_iso(value: datetime | None, timezone_name: str = "Europe/Rome") -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(timezone_name)).isoformat()


def list_courses_data(*, status: str | None = None, upcoming_only: bool = False, limit: int = 25) -> dict:
    query = Course.query
    if status:
        query = query.filter(Course.status == status)
    courses = query.order_by(Course.created_at.desc()).limit(max(1, min(limit, 100))).all()
    today = date.today()
    items = []
    for course in courses:
        day = course_date(course) if course.first_session else None
        if upcoming_only and (day is None or day < today):
            continue
        items.append(
            {
                "code": course.code,
                "title": course.title,
                "status": course.status,
                "date": day.isoformat() if day else None,
                "referent": course.referent.display_name,
                "enrolled": len(course.enrollments),
                "pending_admissions": sum(r.status == "pending" for r in course.admission_requests),
            }
        )
    return {"courses": items, "count": len(items)}


def get_course_data(course_code: str) -> dict:
    course = Course.query.filter_by(code=course_code.strip().upper()).first()
    if course is None:
        raise ValueError("Corso non trovato.")
    return {
        "code": course.code,
        "title": course.title,
        "description": course.description,
        "status": course.status,
        "delivery_mode": course.delivery_mode,
        "referent": {"name": course.referent.display_name, "email": course.referent.email},
        "sessions": [
            {
                "title": session.title,
                "starts_at": _local_iso(session.starts_at, course.timezone_name),
                "ends_at": _local_iso(session.ends_at, course.timezone_name),
            }
            for session in course.sessions
        ],
        "document_count": len(course.documents),
        "questionnaires": [
            {
                "title": questionnaire.title,
                "published": questionnaire.is_published,
                "passing_percentage": questionnaire.passing_percentage,
                "max_attempts": questionnaire.max_attempts,
                "question_count": len(questionnaire.questions),
            }
            for questionnaire in course.questionnaires
        ],
        "enrollment_count": len(course.enrollments),
        "pending_admissions": sum(r.status == "pending" for r in course.admission_requests),
        "certificate_validity_months": course.certificate_validity_months,
    }


def pending_admissions_data(*, course_code: str | None = None, limit: int = 50) -> dict:
    query = AdmissionRequest.query.filter_by(status="pending")
    if course_code:
        course = Course.query.filter_by(code=course_code.strip().upper()).first()
        if course is None:
            raise ValueError("Corso non trovato.")
        query = query.filter_by(course_id=course.id)
    requests = query.order_by(AdmissionRequest.created_at).limit(max(1, min(limit, 100))).all()
    return {
        "admissions": [
            {
                "request_id": request.id,
                "course_code": request.course.code,
                "course_title": request.course.title,
                "participant_name": request.participant.display_name,
                "participant_email": request.participant.email,
                "requested_at": request.created_at.isoformat(),
            }
            for request in requests
        ],
        "count": len(requests),
    }


def participant_training_data(email: str) -> dict:
    participant = User.query.filter_by(email=normalize_email(email)).first()
    if participant is None or not participant.has_role("participant"):
        raise ValueError("Partecipante non trovato.")
    enrollments = Enrollment.query.filter_by(participant_user_id=participant.id).all()
    certificates = Certificate.query.filter_by(participant_user_id=participant.id).all()
    return {
        "participant": {
            "name": participant.display_name,
            "email": participant.email,
            "profile_completed": participant.profile_completed,
        },
        "courses": [
            {
                "code": enrollment.course.code,
                "title": enrollment.course.title,
                "date": course_date(enrollment.course).isoformat() if enrollment.course.first_session else None,
                "attendance": enrollment.attendance_status,
                "certificate_available": enrollment.certificate is not None,
            }
            for enrollment in enrollments
        ],
        "certificates": [
            {
                "title": certificate.title_snapshot,
                "course_date": certificate.course_date.isoformat(),
                "expires_at": certificate.expires_at.isoformat() if certificate.expires_at else None,
                "status": certificate.status,
                "verification_status": certificate.verification_status,
            }
            for certificate in certificates
        ],
    }


def expiring_certificates_data(*, days: int = 180, limit: int = 100) -> dict:
    today = date.today()
    end = today + timedelta(days=max(0, min(days, 3650)))
    certificates = (
        Certificate.query.filter(
            Certificate.status == "valid",
            Certificate.verification_status == "verified",
            Certificate.expires_at.is_not(None),
            Certificate.expires_at >= today,
            Certificate.expires_at <= end,
        )
        .order_by(Certificate.expires_at)
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "certificates": [
            {
                "participant": certificate.participant.display_name,
                "participant_email": certificate.participant.email,
                "company": certificate.company.business_name if certificate.company else None,
                "title": certificate.title_snapshot,
                "course_date": certificate.course_date.isoformat(),
                "expires_at": certificate.expires_at.isoformat(),
            }
            for certificate in certificates
        ],
        "count": len(certificates),
    }


def notification_status_data() -> dict:
    counts = {
        status: EmailOutbox.query.filter_by(status=status).count()
        for status in ("pending", "sent", "failed")
    }
    next_messages = (
        EmailOutbox.query.filter_by(status="pending")
        .order_by(EmailOutbox.next_attempt_at)
        .limit(10)
        .all()
    )
    return {
        "counts": counts,
        "next_messages": [
            {
                "type": message.message_type,
                "recipient": message.recipient_email,
                "next_attempt_at": message.next_attempt_at.isoformat(),
                "attempts": message.attempts,
            }
            for message in next_messages
        ],
    }


def enqueue_reminders_data(access: McpAccessToken) -> dict:
    counts = enqueue_reminders()
    actor = access.created_by
    record_event(
        "mcp.reminders_enqueued",
        actor=actor,
        target_type="email_outbox",
        detail={"token_prefix": access.token_prefix, "counts": counts},
    )
    db.session.commit()
    return {"queued": counts, "total": sum(counts.values()), "emails_were_sent": False}
