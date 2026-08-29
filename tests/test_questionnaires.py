from __future__ import annotations

import io
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from mcorsi.extensions import db
from mcorsi.models import (
    Enrollment,
    Question,
    Questionnaire,
    QuestionnaireAttempt,
    QuestionOption,
    Role,
    User,
)
from mcorsi.services.courses import create_course, duplicate_course
from mcorsi.services.questionnaires import (
    QuestionnaireError,
    attempts_used,
    course_assessment_complete,
    publish_questionnaire,
    start_attempt,
    submit_attempt,
    unpublish_questionnaire,
)
from mcorsi.services.questionnaire_transfer import (
    QuestionnaireTransferError,
    import_questionnaire,
    questionnaire_to_dict,
)


PASSWORD = "PasswordMoltoSicura1!"


def _user(role: str, email: str) -> User:
    user = User(email=email, first_name=email.split("@")[0], profile_completed=True)
    if role in {"admin", "operator"}:
        user.set_password(PASSWORD)
    user.roles.append(Role.query.filter_by(name=role).one())
    if role == "admin":
        user.roles.append(Role.query.filter_by(name="operator").one())
    db.session.add(user)
    db.session.flush()
    return user


def _course(admin: User):
    return create_course(
        actor=admin,
        data={
            "title": "Radioprotezione",
            "description": "Corso di prova",
            "status": "open",
            "referent_user_id": admin.id,
            "session_date": date(2026, 12, 1),
            "start_time": time(9, 0),
            "end_time": time(13, 0),
            "delivery_mode": "online",
            "meeting_url": "",
            "certificate_validity_months": 60,
        },
    )


def _questionnaire(course) -> Questionnaire:
    questionnaire = Questionnaire(
        course=course,
        title="Valutazione finale",
        instructions="Rispondi a tutte le domande.",
        passing_percentage=75,
        max_attempts=3,
        sort_order=1,
    )
    single = Question(
        questionnaire=questionnaire,
        prompt="Il piombo scherma le radiazioni?",
        response_type="single",
        sort_order=1,
    )
    single.options.extend(
        [
            QuestionOption(text="Vero", is_correct=True, score_value=Decimal("2"), sort_order=1),
            QuestionOption(text="Falso", is_correct=False, score_value=Decimal("0"), sort_order=2),
        ]
    )
    multiple = Question(
        questionnaire=questionnaire,
        prompt="Seleziona i dispositivi corretti.",
        response_type="multiple",
        sort_order=2,
    )
    multiple.options.extend(
        [
            QuestionOption(text="Dosimetro", is_correct=True, score_value=Decimal("1"), sort_order=1),
            QuestionOption(text="Schermo", is_correct=True, score_value=Decimal("1"), sort_order=2),
            QuestionOption(text="Accessorio errato", is_correct=False, score_value=Decimal("0"), sort_order=3),
        ]
    )
    db.session.add(questionnaire)
    db.session.flush()
    return questionnaire


def test_scoring_partial_points_pass_and_course_gate(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        participant = _user("participant", "persona@example.it")
        course = _course(admin)
        questionnaire = _questionnaire(course)
        db.session.add(Enrollment(course=course, participant=participant))
        publish_questionnaire(questionnaire, actor=admin)
        db.session.commit()

        single, multiple = questionnaire.questions
        first = start_attempt(questionnaire, participant)
        submit_attempt(
            first,
            {
                single.id: [single.options[0].id],
                multiple.id: [multiple.options[0].id, multiple.options[2].id],
            },
        )
        db.session.commit()
        assert first.score == Decimal("2.00")
        assert first.maximum_score == Decimal("4.00")
        assert first.passed is False
        assert len(first.answers) == 2
        assert first.answers[1].awarded_score == Decimal("0.00")

        second = start_attempt(questionnaire, participant)
        submit_attempt(
            second,
            {
                single.id: [single.options[0].id],
                multiple.id: [multiple.options[0].id],
            },
        )
        db.session.commit()
        assert second.score == Decimal("3.00")
        assert second.passed is True
        assert course_assessment_complete(course, participant) is True
        with pytest.raises(QuestionnaireError, match="già superato"):
            start_attempt(questionnaire, participant)
        with pytest.raises(QuestionnaireError, match="tentativi"):
            unpublish_questionnaire(questionnaire, actor=admin)


def test_three_failed_attempts_are_final(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        participant = _user("participant", "persona@example.it")
        course = _course(admin)
        questionnaire = _questionnaire(course)
        db.session.add(Enrollment(course=course, participant=participant))
        publish_questionnaire(questionnaire, actor=admin)
        db.session.commit()
        single, multiple = questionnaire.questions
        for number in range(1, 4):
            attempt = start_attempt(questionnaire, participant)
            assert attempt.attempt_number == number
            submit_attempt(
                attempt,
                {
                    single.id: [single.options[1].id],
                    multiple.id: [multiple.options[2].id],
                },
            )
            db.session.commit()
            assert attempt.passed is False
        with pytest.raises(QuestionnaireError, match="esaurito"):
            start_attempt(questionnaire, participant)
        assert QuestionnaireAttempt.query.count() == 3


def test_open_attempt_expires_and_consumes_an_attempt(app):
    with app.app_context():
        app.config["QUESTIONNAIRE_ATTEMPT_EXPIRY_MINUTES"] = 15
        admin = _user("admin", "admin@example.it")
        participant = _user("participant", "persona@example.it")
        course = _course(admin)
        questionnaire = _questionnaire(course)
        questionnaire.max_attempts = 2
        db.session.add(Enrollment(course=course, participant=participant))
        publish_questionnaire(questionnaire, actor=admin)
        db.session.commit()

        first = start_attempt(questionnaire, participant)
        assert first.expires_at > datetime.now(timezone.utc)
        assert start_attempt(questionnaire, participant).id == first.id
        assert attempts_used(questionnaire, participant) == 1

        first.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        second = start_attempt(questionnaire, participant)
        assert first.expired_at is not None
        assert first.open_slot is None
        assert second.attempt_number == 2
        assert attempts_used(questionnaire, participant) == 2

        second.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        with pytest.raises(QuestionnaireError, match="esaurito"):
            start_attempt(questionnaire, participant)
        assert second.expired_at is not None
        assert second.open_slot is None


def test_expired_attempt_cannot_be_submitted(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        participant = _user("participant", "persona@example.it")
        course = _course(admin)
        questionnaire = _questionnaire(course)
        db.session.add(Enrollment(course=course, participant=participant))
        publish_questionnaire(questionnaire, actor=admin)
        db.session.commit()

        attempt = start_attempt(questionnaire, participant)
        attempt.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        with pytest.raises(QuestionnaireError, match="scaduto"):
            submit_attempt(attempt, {})
        assert attempt.expired_at is not None
        assert attempt.open_slot is None


def test_database_allows_only_one_open_attempt(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        participant = _user("participant", "persona@example.it")
        course = _course(admin)
        questionnaire = _questionnaire(course)
        db.session.add(Enrollment(course=course, participant=participant))
        publish_questionnaire(questionnaire, actor=admin)
        db.session.commit()

        start_attempt(questionnaire, participant)
        db.session.add(
            QuestionnaireAttempt(
                questionnaire=questionnaire,
                participant=participant,
                attempt_number=2,
                passing_percentage_snapshot=questionnaire.passing_percentage,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
                open_slot=True,
            )
        )
        with pytest.raises(IntegrityError):
            db.session.flush()


def test_course_duplication_clones_questionnaire_as_independent_draft(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        course = _course(admin)
        source = _questionnaire(course)
        source.max_attempts = 7
        publish_questionnaire(source, actor=admin)
        db.session.commit()
        duplicated = duplicate_course(
            course,
            actor=admin,
            referent_user_id=admin.id,
            day=date(2027, 2, 1),
            start_time=time(14, 0),
            end_time=time(18, 0),
        )
        db.session.commit()
        cloned = duplicated.questionnaires[0]
        assert cloned.id != source.id
        assert cloned.is_published is False
        assert cloned.version == source.version + 1
        assert cloned.max_attempts == 7
        assert cloned.maximum_score == source.maximum_score
        assert cloned.questions[0].id != source.questions[0].id
        assert cloned.questions[0].options[0].id != source.questions[0].options[0].id
        assert cloned.attempts == []


def test_operator_builder_creates_and_publishes_valid_questionnaire(app, client):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        course = _course(admin)
        db.session.commit()
        course_id = course.id
    assert client.post(
        "/auth/login", data={"email": "admin@example.it", "password": PASSWORD}
    ).status_code == 302
    created = client.post(
        f"/courses/{course_id}/questionnaires/new",
        data={
            "title": "Test finale",
            "instructions": "Scegli la risposta.",
            "passing_percentage": "70",
        },
    )
    assert created.status_code == 302
    with app.app_context():
        questionnaire_id = Questionnaire.query.one().id
    question = client.post(
        f"/questionnaires/{questionnaire_id}/questions/new",
        data={
            "prompt": "La risposta corretta è vero?",
            "response_type": "single",
            "option_1_text": "Vero",
            "option_1_correct": "y",
            "option_1_score": "2",
            "option_2_text": "Falso",
            "option_2_score": "0",
            "option_3_text": "",
            "option_3_score": "0",
            "option_4_text": "",
            "option_4_score": "0",
            "option_5_text": "",
            "option_5_score": "0",
            "option_6_text": "",
            "option_6_score": "0",
        },
    )
    assert question.status_code == 302
    published = client.post(f"/questionnaires/{questionnaire_id}/publish", data={})
    assert published.status_code == 302
    page = client.get(f"/questionnaires/{questionnaire_id}")
    assert page.status_code == 200
    assert b"Pubblicato" in page.data
    with app.app_context():
        questionnaire = db.session.get(Questionnaire, questionnaire_id)
        assert questionnaire.is_published is True
        assert questionnaire.maximum_score == Decimal("2.00")


def test_invalid_questionnaire_cannot_be_published(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        course = _course(admin)
        questionnaire = Questionnaire(
            course=course, title="Vuoto", passing_percentage=70, max_attempts=3, sort_order=1
        )
        db.session.add(questionnaire)
        db.session.flush()
        with pytest.raises(QuestionnaireError, match="almeno una domanda"):
            publish_questionnaire(questionnaire, actor=admin)


def test_participant_can_complete_questionnaire_from_mobile_flow(app, client):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        participant = _user("participant", "persona@example.it")
        course = _course(admin)
        questionnaire = _questionnaire(course)
        db.session.add(Enrollment(course=course, participant=participant))
        publish_questionnaire(questionnaire, actor=admin)
        db.session.commit()
        participant_id = participant.id
        questionnaire_id = questionnaire.id
        selections = {
            f"question_{questionnaire.questions[0].id}": questionnaire.questions[0].options[0].id,
            f"question_{questionnaire.questions[1].id}": [
                questionnaire.questions[1].options[0].id,
                questionnaire.questions[1].options[1].id,
            ],
        }
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = participant_id
        browser_session["_fresh"] = True
    started = client.post(f"/participant/questionnaires/{questionnaire_id}/start", data={})
    assert started.status_code == 302
    attempt_url = started.headers["Location"]
    assert client.get(attempt_url).status_code == 200
    submitted = client.post(attempt_url, data={**selections, "submit": "Invia risposte"})
    assert submitted.status_code == 302
    result = client.get(submitted.headers["Location"])
    assert result.status_code == 200
    assert b"Questionario superato" in result.data


def test_staff_archive_preview_export_duplicate_and_json_import(app, client):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        source_course = _course(admin)
        target_course = _course(admin)
        questionnaire = _questionnaire(source_course)
        questionnaire.max_attempts = 7
        db.session.commit()
        questionnaire_id = questionnaire.id
        target_course_id = target_course.id

    assert client.post(
        "/auth/login", data={"email": "admin@example.it", "password": PASSWORD}
    ).status_code == 302

    archive = client.get("/questionnaires")
    assert archive.status_code == 200
    assert b"Archivio questionari" in archive.data
    assert b"Valutazione finale" in archive.data

    preview = client.get(f"/questionnaires/{questionnaire_id}/preview")
    assert preview.status_code == 200
    assert b"Anteprima partecipante" in preview.data
    assert b"Il piombo scherma le radiazioni?" in preview.data
    assert b"Corretta" not in preview.data

    exported = client.get(f"/questionnaires/{questionnaire_id}/export.json")
    assert exported.status_code == 200
    payload = json.loads(exported.data)
    assert payload["format"] == "mcorsi.questionnaire"
    assert payload["schema_version"] == 1
    assert payload["questionnaire"]["max_attempts"] == 7
    assert payload["questionnaire"]["questions"][0]["options"][0]["is_correct"] is True
    assert "attempts" not in payload["questionnaire"]
    assert "id" not in payload["questionnaire"]

    markdown = client.get(f"/questionnaires/{questionnaire_id}/export.md")
    assert markdown.status_code == 200
    assert b"# Valutazione finale" in markdown.data
    assert b"[x] Vero" in markdown.data

    duplicated = client.post(
        f"/questionnaires/{questionnaire_id}/duplicate",
        data={"course_id": target_course_id},
    )
    assert duplicated.status_code == 302

    imported = client.post(
        "/questionnaires/import",
        data={
            "import-course_id": target_course_id,
            "import-file": (io.BytesIO(exported.data), "questionario.json"),
        },
        content_type="multipart/form-data",
    )
    assert imported.status_code == 302

    with app.app_context():
        copies = Questionnaire.query.filter_by(course_id=target_course_id).order_by(
            Questionnaire.sort_order
        ).all()
        assert len(copies) == 2
        assert all(item.is_published is False for item in copies)
        assert all(item.attempts == [] for item in copies)
        assert all(item.version == 2 for item in copies)
        assert all(item.max_attempts == 7 for item in copies)
        assert all(len(item.questions) == 2 for item in copies)
        assert copies[0].questions[0].id != copies[1].questions[0].id


def test_questionnaire_import_defaults_missing_max_attempts_to_three(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        source_course = _course(admin)
        target_course = _course(admin)
        payload = questionnaire_to_dict(_questionnaire(source_course))
        payload["questionnaire"].pop("max_attempts")

        imported = import_questionnaire(payload, course=target_course, actor=admin)

        assert imported.max_attempts == 3


@pytest.mark.parametrize("invalid_max_attempts", [0, 21, True])
def test_questionnaire_import_rejects_invalid_max_attempts(app, invalid_max_attempts):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        source_course = _course(admin)
        target_course = _course(admin)
        payload = questionnaire_to_dict(_questionnaire(source_course))
        payload["questionnaire"]["max_attempts"] = invalid_max_attempts

        with pytest.raises(QuestionnaireTransferError, match="max_attempts"):
            import_questionnaire(payload, course=target_course, actor=admin)


def test_invalid_questionnaire_json_is_rejected_without_partial_data(app, client):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        course = _course(admin)
        db.session.commit()
        course_id = course.id
    client.post("/auth/login", data={"email": "admin@example.it", "password": PASSWORD})
    invalid = {
        "format": "mcorsi.questionnaire",
        "schema_version": 1,
        "questionnaire": {
            "title": "Non valido",
            "passing_percentage": 70,
            "questions": [],
        },
    }
    response = client.post(
        "/questionnaires/import",
        data={
            "import-course_id": course_id,
            "import-file": (
                io.BytesIO(json.dumps(invalid).encode("utf-8")),
                "questionario.json",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Importazione non riuscita" in response.data
    with app.app_context():
        assert Questionnaire.query.count() == 0
