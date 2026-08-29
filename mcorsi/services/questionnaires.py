from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    AttemptAnswer,
    Enrollment,
    Question,
    Questionnaire,
    QuestionnaireAttempt,
    QuestionOption,
    User,
)
from .audit import record_event


class QuestionnaireError(ValueError):
    pass


def ensure_editable(questionnaire: Questionnaire) -> None:
    if questionnaire.has_attempts:
        raise QuestionnaireError(
            "Il questionario non è più modificabile perché esistono già dei tentativi."
        )


def ensure_draft_editable(questionnaire: Questionnaire) -> None:
    ensure_editable(questionnaire)
    if questionnaire.is_published:
        raise QuestionnaireError("Sospendi la pubblicazione prima di modificare il questionario.")


def validation_errors(questionnaire: Questionnaire) -> list[str]:
    errors: list[str] = []
    if not questionnaire.questions:
        errors.append("Aggiungi almeno una domanda.")
    for number, question in enumerate(questionnaire.questions, start=1):
        if len(question.options) < 2:
            errors.append(f"La domanda {number} deve avere almeno due opzioni.")
            continue
        correct = [option for option in question.options if option.is_correct]
        if not correct:
            errors.append(f"La domanda {number} non ha risposte corrette.")
        if question.response_type == "single" and len(correct) != 1:
            errors.append(f"La domanda {number} a scelta singola deve avere una sola risposta corretta.")
        if any(option.score_value <= 0 for option in correct):
            errors.append(f"Le risposte corrette della domanda {number} devono avere punteggio positivo.")
        if any(option.score_value != 0 for option in question.options if not option.is_correct):
            errors.append(f"Le risposte errate della domanda {number} devono avere punteggio zero.")
    if questionnaire.maximum_score <= 0:
        errors.append("Il punteggio massimo deve essere maggiore di zero.")
    return errors


def publish_questionnaire(questionnaire: Questionnaire, *, actor: User) -> None:
    ensure_editable(questionnaire)
    errors = validation_errors(questionnaire)
    if errors:
        raise QuestionnaireError(" ".join(errors))
    questionnaire.is_published = True
    questionnaire.published_at = datetime.now(timezone.utc)
    questionnaire.published_by_user_id = actor.id
    record_event(
        "questionnaire.published",
        actor=actor,
        target_type="questionnaire",
        target_id=questionnaire.id,
        detail={"course_id": questionnaire.course_id, "maximum_score": str(questionnaire.maximum_score)},
    )


def unpublish_questionnaire(questionnaire: Questionnaire, *, actor: User) -> None:
    ensure_editable(questionnaire)
    questionnaire.is_published = False
    questionnaire.published_at = None
    questionnaire.published_by_user_id = None
    record_event(
        "questionnaire.unpublished",
        actor=actor,
        target_type="questionnaire",
        target_id=questionnaire.id,
    )


def replace_question_options(question: Question, option_data: list[dict]) -> None:
    ensure_draft_editable(question.questionnaire)
    populated = [item for item in option_data if item["text"].strip()]
    if len(populated) < 2:
        raise QuestionnaireError("Inserisci almeno due opzioni.")
    correct = [item for item in populated if item["is_correct"]]
    if not correct:
        raise QuestionnaireError("Indica almeno una risposta corretta.")
    if question.response_type == "single" and len(correct) != 1:
        raise QuestionnaireError("Una domanda a scelta singola richiede una sola risposta corretta.")
    for item in correct:
        if Decimal(str(item["score_value"] or 0)) <= 0:
            raise QuestionnaireError("Ogni risposta corretta deve avere un punteggio positivo.")
    question.options.clear()
    db.session.flush()
    for index, item in enumerate(populated, start=1):
        score = Decimal(str(item["score_value"] or 0)) if item["is_correct"] else Decimal("0")
        question.options.append(
            QuestionOption(
                text=item["text"].strip(),
                is_correct=item["is_correct"],
                score_value=score,
                sort_order=index,
            )
        )


def participant_can_take(questionnaire: Questionnaire, participant: User) -> bool:
    enrolled = Enrollment.query.filter_by(
        course_id=questionnaire.course_id, participant_user_id=participant.id
    ).first()
    return bool(
        enrolled
        and questionnaire.is_published
        and questionnaire.course.status in {"open", "in_progress", "completed"}
    )


def has_passed(questionnaire: Questionnaire, participant: User) -> bool:
    return (
        QuestionnaireAttempt.query.filter_by(
            questionnaire_id=questionnaire.id,
            participant_user_id=participant.id,
            passed=True,
        ).first()
        is not None
    )


def submitted_attempts(questionnaire: Questionnaire, participant: User) -> list[QuestionnaireAttempt]:
    return (
        QuestionnaireAttempt.query.filter_by(
            questionnaire_id=questionnaire.id, participant_user_id=participant.id
        )
        .filter(QuestionnaireAttempt.submitted_at.is_not(None))
        .order_by(QuestionnaireAttempt.attempt_number)
        .all()
    )


def attempts_used(questionnaire: Questionnaire, participant: User) -> int:
    return QuestionnaireAttempt.query.filter_by(
        questionnaire_id=questionnaire.id,
        participant_user_id=participant.id,
    ).count()


def expire_attempt(
    attempt: QuestionnaireAttempt, *, now: datetime | None = None
) -> bool:
    if attempt.submitted_at is not None or not attempt.is_expired:
        return False
    expired_at = now or datetime.now(timezone.utc)
    was_open = attempt.expired_at is None or attempt.open_slot is True
    attempt.expired_at = attempt.expired_at or expired_at
    attempt.open_slot = None
    if was_open:
        record_event(
            "questionnaire.attempt_expired",
            actor=attempt.participant,
            target_type="questionnaire_attempt",
            target_id=attempt.id,
            detail={
                "questionnaire_id": attempt.questionnaire_id,
                "attempt_number": attempt.attempt_number,
            },
        )
    return was_open


def expire_open_attempts(questionnaire: Questionnaire, participant: User) -> bool:
    changed = False
    open_attempts = QuestionnaireAttempt.query.filter_by(
        questionnaire_id=questionnaire.id,
        participant_user_id=participant.id,
        submitted_at=None,
        open_slot=True,
    ).all()
    for attempt in open_attempts:
        changed = expire_attempt(attempt) or changed
    return changed


def start_attempt(questionnaire: Questionnaire, participant: User) -> QuestionnaireAttempt:
    if not participant_can_take(questionnaire, participant):
        raise QuestionnaireError("Il questionario non è disponibile per questo account.")
    if has_passed(questionnaire, participant):
        raise QuestionnaireError("Hai già superato questo questionario.")
    expire_open_attempts(questionnaire, participant)
    unfinished = QuestionnaireAttempt.query.filter_by(
        questionnaire_id=questionnaire.id,
        participant_user_id=participant.id,
        submitted_at=None,
        open_slot=True,
    ).first()
    if unfinished:
        return unfinished
    used = attempts_used(questionnaire, participant)
    if used >= questionnaire.max_attempts:
        raise QuestionnaireError("Hai esaurito i tentativi disponibili.")
    latest_number = (
        db.session.query(db.func.max(QuestionnaireAttempt.attempt_number))
        .filter_by(
            questionnaire_id=questionnaire.id,
            participant_user_id=participant.id,
        )
        .scalar()
        or 0
    )
    expiry_minutes = max(
        1, int(current_app.config["QUESTIONNAIRE_ATTEMPT_EXPIRY_MINUTES"])
    )
    attempt = QuestionnaireAttempt(
        questionnaire_id=questionnaire.id,
        participant_user_id=participant.id,
        attempt_number=latest_number + 1,
        passing_percentage_snapshot=questionnaire.passing_percentage,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
        open_slot=True,
    )
    try:
        with db.session.begin_nested():
            db.session.add(attempt)
            db.session.flush()
    except IntegrityError:
        concurrent = QuestionnaireAttempt.query.filter_by(
            questionnaire_id=questionnaire.id,
            participant_user_id=participant.id,
            submitted_at=None,
            open_slot=True,
        ).first()
        if concurrent and not concurrent.is_expired:
            return concurrent
        raise QuestionnaireError(
            "Non è stato possibile avviare il tentativo. Riprova."
        ) from None
    record_event(
        "questionnaire.attempt_started",
        actor=participant,
        target_type="questionnaire_attempt",
        target_id=attempt.id,
        detail={"questionnaire_id": questionnaire.id, "attempt_number": attempt.attempt_number},
    )
    return attempt


def submit_attempt(attempt: QuestionnaireAttempt, selections: dict[str, list[str]]) -> QuestionnaireAttempt:
    if attempt.submitted_at is not None:
        raise QuestionnaireError("Questo tentativo è già stato inviato.")
    if attempt.is_expired:
        expire_attempt(attempt)
        raise QuestionnaireError("Questo tentativo è scaduto. Avviane uno nuovo.")
    questionnaire = attempt.questionnaire
    if not participant_can_take(questionnaire, attempt.participant):
        raise QuestionnaireError("Il questionario non è più disponibile.")

    score = Decimal("0")
    maximum = questionnaire.maximum_score
    if maximum <= 0:
        raise QuestionnaireError("Il questionario non ha un punteggio valido.")
    answers: list[AttemptAnswer] = []
    snapshot: list[dict] = []
    for question in questionnaire.questions:
        selected = set(selections.get(question.id, []))
        if not selected:
            raise QuestionnaireError("Rispondi a tutte le domande prima di inviare.")
        if question.response_type == "single" and len(selected) != 1:
            raise QuestionnaireError("Seleziona una sola risposta per ogni domanda a scelta singola.")
        option_by_id = {option.id: option for option in question.options}
        if not selected.issubset(option_by_id):
            raise QuestionnaireError("Una delle risposte selezionate non è valida.")
        correct_ids = {option.id for option in question.options if option.is_correct}
        contains_wrong = bool(selected - correct_ids)
        awarded = Decimal("0")
        if not contains_wrong:
            awarded = sum(
                (option_by_id[option_id].score_value for option_id in selected), Decimal("0")
            )
        fully_correct = selected == correct_ids
        score += awarded
        answer = AttemptAnswer(
            question=question,
            selected_option_ids=sorted(selected),
            awarded_score=awarded,
            fully_correct=fully_correct,
        )
        answers.append(answer)
        snapshot.append(
            {
                "question_id": question.id,
                "prompt": question.prompt,
                "response_type": question.response_type,
                "selected_option_ids": sorted(selected),
                "selected_option_texts": [option_by_id[item].text for item in sorted(selected)],
                "correct_option_ids": sorted(correct_ids),
                "awarded_score": str(awarded),
            }
        )

    attempt.answers.extend(answers)
    attempt.score = score
    attempt.maximum_score = maximum
    attempt.submitted_at = datetime.now(timezone.utc)
    attempt.open_slot = None
    attempt.passed = (score * Decimal("100") / maximum) >= Decimal(
        attempt.passing_percentage_snapshot
    )
    attempt.answers_snapshot = snapshot
    record_event(
        "questionnaire.attempt_submitted",
        actor=attempt.participant,
        target_type="questionnaire_attempt",
        target_id=attempt.id,
        detail={
            "questionnaire_id": questionnaire.id,
            "attempt_number": attempt.attempt_number,
            "score": str(score),
            "maximum_score": str(maximum),
            "passed": attempt.passed,
        },
    )
    return attempt


def course_assessment_complete(course, participant: User) -> bool:
    published = [item for item in course.questionnaires if item.is_published]
    return bool(published) and all(has_passed(item, participant) for item in published)
