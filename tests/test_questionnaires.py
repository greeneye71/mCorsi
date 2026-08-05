from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

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
    course_assessment_complete,
    publish_questionnaire,
    start_attempt,
    submit_attempt,
    unpublish_questionnaire,
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


def test_course_duplication_clones_questionnaire_as_independent_draft(app):
    with app.app_context():
        admin = _user("admin", "admin@example.it")
        course = _course(admin)
        source = _questionnaire(course)
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
