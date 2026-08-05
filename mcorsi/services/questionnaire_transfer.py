from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ..extensions import db
from ..models import Course, Question, Questionnaire, QuestionOption, User
from .audit import record_event
from .questionnaires import QuestionnaireError, validation_errors


FORMAT_NAME = "mcorsi.questionnaire"
SCHEMA_VERSION = 1
MAX_QUESTIONS = 500
MAX_OPTIONS = 6


class QuestionnaireTransferError(QuestionnaireError):
    pass


def questionnaire_to_dict(questionnaire: Questionnaire) -> dict[str, Any]:
    """Return the portable definition only, never attempts or participant data."""
    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "questionnaire": {
            "title": questionnaire.title,
            "instructions": questionnaire.instructions,
            "passing_percentage": questionnaire.passing_percentage,
            "max_attempts": questionnaire.max_attempts,
            "version": questionnaire.version,
            "questions": [
                {
                    "prompt": question.prompt,
                    "response_type": question.response_type,
                    "options": [
                        {
                            "text": option.text,
                            "is_correct": option.is_correct,
                            "score": str(option.score_value),
                        }
                        for option in question.options
                    ],
                }
                for question in questionnaire.questions
            ],
        },
    }


def questionnaire_to_markdown(questionnaire: Questionnaire) -> str:
    lines = [
        f"# {questionnaire.title}",
        "",
        f"- Corso: {questionnaire.course.title} ({questionnaire.course.code})",
        f"- Soglia: {questionnaire.passing_percentage}%",
        f"- Tentativi consentiti: {questionnaire.max_attempts}",
        f"- Versione: {questionnaire.version}",
        "",
    ]
    if questionnaire.instructions:
        lines.extend([questionnaire.instructions, ""])
    lines.extend(
        [
            "> Documento per gli operatori: contiene anche le soluzioni e i punteggi.",
            "",
        ]
    )
    for number, question in enumerate(questionnaire.questions, start=1):
        kind = "scelta multipla" if question.response_type == "multiple" else "scelta singola"
        lines.extend([f"## {number}. {question.prompt}", "", f"Tipo: {kind}", ""])
        for option in question.options:
            marker = "x" if option.is_correct else " "
            score = f" — {option.score_value} punti" if option.is_correct else ""
            lines.append(f"- [{marker}] {option.text}{score}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _text(value: Any, field: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise QuestionnaireTransferError(f"Il campo '{field}' deve essere testuale.")
    value = value.strip()
    if required and not value:
        raise QuestionnaireTransferError(f"Il campo '{field}' è obbligatorio.")
    if len(value) > maximum:
        raise QuestionnaireTransferError(f"Il campo '{field}' supera {maximum} caratteri.")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise QuestionnaireTransferError(f"Il campo '{field}' non è valido.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise QuestionnaireTransferError(f"Il campo '{field}' deve essere un numero intero.") from exc
    if result < minimum or result > maximum:
        raise QuestionnaireTransferError(
            f"Il campo '{field}' deve essere compreso tra {minimum} e {maximum}."
        )
    return result


def _score(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuestionnaireTransferError(f"Il campo '{field}' non è un punteggio valido.") from exc
    if not result.is_finite() or result < 0 or result > Decimal("10000"):
        raise QuestionnaireTransferError(f"Il campo '{field}' deve essere compreso tra 0 e 10000.")
    if result.as_tuple().exponent < -2:
        raise QuestionnaireTransferError(f"Il campo '{field}' può avere al massimo due decimali.")
    return result


def _definition(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise QuestionnaireTransferError("Il contenuto JSON deve essere un oggetto.")
    if payload.get("format") != FORMAT_NAME:
        raise QuestionnaireTransferError("Formato non riconosciuto: atteso mcorsi.questionnaire.")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise QuestionnaireTransferError(
            f"Versione del formato non supportata: è richiesta la versione {SCHEMA_VERSION}."
        )
    definition = payload.get("questionnaire")
    if not isinstance(definition, dict):
        raise QuestionnaireTransferError("La definizione del questionario non è presente.")
    return definition


def _build_questionnaire(
    definition: dict[str, Any], *, course: Course, source_version_increment: bool
) -> Questionnaire:
    title = _text(definition.get("title"), "title", 240)
    instructions = _text(definition.get("instructions", ""), "instructions", 5000, required=False)
    passing = _integer(definition.get("passing_percentage"), "passing_percentage", 1, 100)
    source_version = _integer(definition.get("version", 1), "version", 1, 1_000_000)
    questions = definition.get("questions")
    if not isinstance(questions, list) or not questions:
        raise QuestionnaireTransferError("Il questionario deve contenere almeno una domanda.")
    if len(questions) > MAX_QUESTIONS:
        raise QuestionnaireTransferError(f"Sono consentite al massimo {MAX_QUESTIONS} domande.")

    questionnaire = Questionnaire(
        course=course,
        title=title,
        instructions=instructions,
        passing_percentage=passing,
        max_attempts=3,
        sort_order=max((item.sort_order for item in course.questionnaires), default=0) + 1,
        version=source_version + 1 if source_version_increment else source_version,
        is_published=False,
    )
    for question_number, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise QuestionnaireTransferError(f"La domanda {question_number} non è valida.")
        response_type = item.get("response_type")
        if response_type not in {"single", "multiple"}:
            raise QuestionnaireTransferError(
                f"Il tipo della domanda {question_number} deve essere 'single' o 'multiple'."
            )
        options = item.get("options")
        if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
            raise QuestionnaireTransferError(
                f"La domanda {question_number} deve avere da 2 a {MAX_OPTIONS} opzioni."
            )
        question = Question(
            questionnaire=questionnaire,
            prompt=_text(item.get("prompt"), f"questions[{question_number}].prompt", 5000),
            response_type=response_type,
            sort_order=question_number,
        )
        for option_number, option_data in enumerate(options, start=1):
            if not isinstance(option_data, dict) or not isinstance(option_data.get("is_correct"), bool):
                raise QuestionnaireTransferError(
                    f"L'opzione {option_number} della domanda {question_number} non è valida."
                )
            is_correct = option_data["is_correct"]
            score = _score(
                option_data.get("score", 0),
                f"questions[{question_number}].options[{option_number}].score",
            )
            question.options.append(
                QuestionOption(
                    text=_text(
                        option_data.get("text"),
                        f"questions[{question_number}].options[{option_number}].text",
                        2000,
                    ),
                    is_correct=is_correct,
                    score_value=score if is_correct else Decimal("0"),
                    sort_order=option_number,
                )
            )
    errors = validation_errors(questionnaire)
    if errors:
        raise QuestionnaireTransferError(" ".join(errors))
    return questionnaire


def import_questionnaire(payload: Any, *, course: Course, actor: User) -> Questionnaire:
    questionnaire = _build_questionnaire(
        _definition(payload), course=course, source_version_increment=True
    )
    db.session.add(questionnaire)
    record_event(
        "questionnaire.imported",
        actor=actor,
        target_type="questionnaire",
        target_id=questionnaire.id,
        detail={"course_id": course.id, "format_version": SCHEMA_VERSION},
    )
    return questionnaire


def duplicate_questionnaire(
    source: Questionnaire, *, course: Course, actor: User
) -> Questionnaire:
    questionnaire = _build_questionnaire(
        questionnaire_to_dict(source)["questionnaire"],
        course=course,
        source_version_increment=True,
    )
    db.session.add(questionnaire)
    record_event(
        "questionnaire.duplicated",
        actor=actor,
        target_type="questionnaire",
        target_id=questionnaire.id,
        detail={"source_questionnaire_id": source.id, "course_id": course.id},
    )
    return questionnaire
