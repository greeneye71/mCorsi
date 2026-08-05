from __future__ import annotations

import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    AdmissionRequest,
    Course,
    CourseDocument,
    CourseSession,
    Enrollment,
    Question,
    Questionnaire,
    QuestionOption,
    User,
)
from .audit import record_event


COURSE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CourseOperationError(ValueError):
    pass


def generate_course_code(length: int = 10) -> str:
    for _attempt in range(20):
        code = "".join(secrets.choice(COURSE_CODE_ALPHABET) for _ in range(length))
        if not Course.query.filter_by(code=code).first():
            return code
    raise RuntimeError("Impossibile generare un codice corso univoco.")


def local_datetime(day, clock, timezone_name: str = "Europe/Rome") -> datetime:
    local = datetime.combine(day, clock, tzinfo=ZoneInfo(timezone_name))
    return local.astimezone(timezone.utc)


def set_single_session(course: Course, day, start_time, end_time) -> None:
    timezone_name = course.timezone_name or "Europe/Rome"
    starts_at = local_datetime(day, start_time, timezone_name)
    ends_at = local_datetime(day, end_time, timezone_name)
    if ends_at <= starts_at:
        raise CourseOperationError("L'ora finale deve essere successiva a quella iniziale.")
    if course.sessions:
        session = course.sessions[0]
        session.starts_at = starts_at
        session.ends_at = ends_at
    else:
        course.sessions.append(
            CourseSession(sequence=1, title="Seduta unica", starts_at=starts_at, ends_at=ends_at)
        )


def create_course(*, actor: User, data: dict) -> Course:
    course = Course(
        title=data["title"].strip(),
        description=data.get("description", "").strip(),
        code=generate_course_code(),
        status=data["status"],
        creator_user_id=actor.id,
        referent_user_id=data["referent_user_id"],
        delivery_mode=data["delivery_mode"],
        meeting_url=data.get("meeting_url", "").strip(),
        certificate_validity_months=data.get("certificate_validity_months"),
        timezone_name="Europe/Rome",
    )
    set_single_session(course, data["session_date"], data["start_time"], data["end_time"])
    db.session.add(course)
    record_event(
        "course.created",
        actor=actor,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title, "code": course.code},
    )
    return course


def update_course(course: Course, *, actor: User, data: dict) -> Course:
    before = {"title": course.title, "status": course.status, "referent": course.referent_user_id}
    course.title = data["title"].strip()
    course.description = data.get("description", "").strip()
    course.status = data["status"]
    course.referent_user_id = data["referent_user_id"]
    course.delivery_mode = data["delivery_mode"]
    course.meeting_url = data.get("meeting_url", "").strip()
    course.certificate_validity_months = data.get("certificate_validity_months")
    set_single_session(course, data["session_date"], data["start_time"], data["end_time"])
    record_event(
        "course.updated",
        actor=actor,
        target_type="course",
        target_id=course.id,
        detail={"before": before, "after": {"title": course.title, "status": course.status, "referent": course.referent_user_id}},
    )
    return course


def duplicate_course(source: Course, *, actor: User, referent_user_id: str, day, start_time, end_time) -> Course:
    duplicate = Course(
        title=source.title,
        description=source.description,
        code=generate_course_code(),
        status="draft",
        creator_user_id=actor.id,
        referent_user_id=referent_user_id,
        delivery_mode=source.delivery_mode,
        meeting_url=source.meeting_url,
        timezone_name=source.timezone_name,
        certificate_validity_months=source.certificate_validity_months,
        certificate_template_id=source.certificate_template_id,
        signature_asset_id=source.signature_asset_id,
    )
    set_single_session(duplicate, day, start_time, end_time)
    for document in source.documents:
        duplicate.documents.append(
            CourseDocument(
                stored_file_id=document.stored_file_id,
                label=document.label,
                sort_order=document.sort_order,
            )
        )
    for source_questionnaire in source.questionnaires:
        questionnaire = Questionnaire(
            title=source_questionnaire.title,
            instructions=source_questionnaire.instructions,
            passing_percentage=source_questionnaire.passing_percentage,
            max_attempts=3,
            sort_order=source_questionnaire.sort_order,
            version=source_questionnaire.version + 1,
            is_published=False,
        )
        for source_question in source_questionnaire.questions:
            question = Question(
                prompt=source_question.prompt,
                response_type=source_question.response_type,
                sort_order=source_question.sort_order,
            )
            for source_option in source_question.options:
                question.options.append(
                    QuestionOption(
                        text=source_option.text,
                        is_correct=source_option.is_correct,
                        score_value=source_option.score_value,
                        sort_order=source_option.sort_order,
                    )
                )
            questionnaire.questions.append(question)
        duplicate.questionnaires.append(questionnaire)
    db.session.add(duplicate)
    record_event(
        "course.duplicated",
        actor=actor,
        target_type="course",
        target_id=duplicate.id,
        detail={"source_course_id": source.id, "new_code": duplicate.code},
    )
    return duplicate


def request_admission(course: Course, participant: User, *, actor: User | None = None) -> AdmissionRequest:
    if not participant.has_role("participant"):
        raise CourseOperationError("L'utente selezionato non è un partecipante.")
    existing = AdmissionRequest.query.filter_by(
        course_id=course.id, participant_user_id=participant.id
    ).first()
    if existing:
        raise CourseOperationError("Esiste già una richiesta per questo partecipante.")
    request = AdmissionRequest(course=course, participant=participant)
    db.session.add(request)
    record_event(
        "admission.requested",
        actor=actor or participant,
        target_type="admission_request",
        target_id=request.id,
        detail={"course_id": course.id, "participant_user_id": participant.id},
    )
    return request


def decide_admission(
    admission: AdmissionRequest,
    *,
    actor: User,
    approve: bool,
    decision_message: str = "",
    internal_note: str = "",
) -> AdmissionRequest:
    if admission.status != "pending":
        raise CourseOperationError("La richiesta è già stata esaminata.")
    admission.status = "approved" if approve else "rejected"
    admission.decided_by_user_id = actor.id
    admission.decided_at = datetime.now(timezone.utc)
    admission.decision_message = decision_message.strip()
    admission.internal_note = internal_note.strip()
    if approve:
        db.session.add(
            Enrollment(
                course=admission.course,
                participant=admission.participant,
                admission_request=admission,
            )
        )
    record_event(
        "admission.approved" if approve else "admission.rejected",
        actor=actor,
        target_type="admission_request",
        target_id=admission.id,
        detail={"course_id": admission.course_id, "participant_user_id": admission.participant_user_id},
    )
    return admission
