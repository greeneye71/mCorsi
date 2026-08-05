from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Question, Questionnaire, QuestionnaireAttempt
from ..services.audit import record_event
from ..services.permissions import participant_required, staff_required
from ..services.questionnaires import (
    QuestionnaireError,
    ensure_draft_editable,
    publish_questionnaire,
    replace_question_options,
    start_attempt,
    submit_attempt,
    submitted_attempts,
    unpublish_questionnaire,
    validation_errors,
)
from .forms import AttemptSubmissionForm, EmptyForm, QuestionForm, QuestionnaireForm


questionnaires_bp = Blueprint("questionnaires", __name__)


def _option_data(form: QuestionForm) -> list[dict]:
    return [
        {
            "text": form[f"option_{index}_text"].data or "",
            "is_correct": form[f"option_{index}_correct"].data,
            "score_value": form[f"option_{index}_score"].data or 0,
        }
        for index in range(1, 7)
    ]


@questionnaires_bp.route("/courses/<course_id>/questionnaires/new", methods=["GET", "POST"])
@staff_required
def create(course_id: str):
    from ..models import Course

    course = db.get_or_404(Course, course_id)
    form = QuestionnaireForm()
    if form.validate_on_submit():
        next_order = max((item.sort_order for item in course.questionnaires), default=0) + 1
        questionnaire = Questionnaire(
            course=course,
            title=form.title.data.strip(),
            instructions=(form.instructions.data or "").strip(),
            passing_percentage=form.passing_percentage.data,
            max_attempts=3,
            sort_order=next_order,
        )
        db.session.add(questionnaire)
        record_event(
            "questionnaire.created",
            actor=current_user,
            target_type="questionnaire",
            target_id=questionnaire.id,
            detail={"course_id": course.id},
        )
        db.session.commit()
        flash("Questionario creato. Ora aggiungi le domande.", "success")
        return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
    return render_template("questionnaires/form.html", form=form, course=course, heading="Nuovo questionario")


@questionnaires_bp.get("/questionnaires/<questionnaire_id>")
@staff_required
def detail(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    return render_template(
        "questionnaires/detail.html",
        questionnaire=questionnaire,
        errors=validation_errors(questionnaire),
        empty_form=EmptyForm(),
    )


@questionnaires_bp.route("/questionnaires/<questionnaire_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    try:
        ensure_draft_editable(questionnaire)
    except QuestionnaireError as exc:
        flash(str(exc), "error")
        return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
    form = QuestionnaireForm(obj=questionnaire)
    if form.validate_on_submit():
        questionnaire.title = form.title.data.strip()
        questionnaire.instructions = (form.instructions.data or "").strip()
        questionnaire.passing_percentage = form.passing_percentage.data
        record_event(
            "questionnaire.updated", actor=current_user, target_type="questionnaire", target_id=questionnaire.id
        )
        db.session.commit()
        flash("Questionario aggiornato.", "success")
        return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
    return render_template(
        "questionnaires/form.html", form=form, course=questionnaire.course, questionnaire=questionnaire, heading="Modifica questionario"
    )


@questionnaires_bp.route("/questionnaires/<questionnaire_id>/questions/new", methods=["GET", "POST"])
@staff_required
def create_question(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    try:
        ensure_draft_editable(questionnaire)
    except QuestionnaireError as exc:
        flash(str(exc), "error")
        return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
    form = QuestionForm()
    if form.validate_on_submit():
        question = Question(
            questionnaire=questionnaire,
            prompt=form.prompt.data.strip(),
            response_type=form.response_type.data,
            sort_order=max((item.sort_order for item in questionnaire.questions), default=0) + 1,
        )
        db.session.add(question)
        try:
            replace_question_options(question, _option_data(form))
            record_event(
                "questionnaire.question_created",
                actor=current_user,
                target_type="question",
                target_id=question.id,
                detail={"questionnaire_id": questionnaire.id},
            )
            db.session.commit()
            flash("Domanda aggiunta.", "success")
            return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
        except QuestionnaireError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("questionnaires/question_form.html", form=form, questionnaire=questionnaire, heading="Nuova domanda")


@questionnaires_bp.route("/questions/<question_id>/edit", methods=["GET", "POST"])
@staff_required
def edit_question(question_id: str):
    question = db.get_or_404(Question, question_id)
    questionnaire = question.questionnaire
    try:
        ensure_draft_editable(questionnaire)
    except QuestionnaireError as exc:
        flash(str(exc), "error")
        return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
    form = QuestionForm(obj=question)
    if not form.is_submitted():
        for index, option in enumerate(question.options[:6], start=1):
            form[f"option_{index}_text"].data = option.text
            form[f"option_{index}_correct"].data = option.is_correct
            form[f"option_{index}_score"].data = option.score_value
    if form.validate_on_submit():
        question.prompt = form.prompt.data.strip()
        question.response_type = form.response_type.data
        try:
            replace_question_options(question, _option_data(form))
            record_event(
                "questionnaire.question_updated",
                actor=current_user,
                target_type="question",
                target_id=question.id,
            )
            db.session.commit()
            flash("Domanda aggiornata.", "success")
            return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
        except QuestionnaireError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("questionnaires/question_form.html", form=form, questionnaire=questionnaire, question=question, heading="Modifica domanda")


@questionnaires_bp.post("/questions/<question_id>/delete")
@staff_required
def delete_question(question_id: str):
    question = db.get_or_404(Question, question_id)
    questionnaire = question.questionnaire
    form = EmptyForm()
    if form.validate_on_submit():
        try:
            ensure_draft_editable(questionnaire)
            db.session.delete(question)
            record_event(
                "questionnaire.question_deleted",
                actor=current_user,
                target_type="questionnaire",
                target_id=questionnaire.id,
            )
            db.session.commit()
            flash("Domanda eliminata.", "success")
        except QuestionnaireError as exc:
            flash(str(exc), "error")
    return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))


@questionnaires_bp.post("/questionnaires/<questionnaire_id>/publish")
@staff_required
def publish(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    form = EmptyForm()
    if form.validate_on_submit():
        try:
            publish_questionnaire(questionnaire, actor=current_user)
            db.session.commit()
            flash("Questionario pubblicato.", "success")
        except QuestionnaireError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))


@questionnaires_bp.post("/questionnaires/<questionnaire_id>/unpublish")
@staff_required
def unpublish(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    form = EmptyForm()
    if form.validate_on_submit():
        try:
            unpublish_questionnaire(questionnaire, actor=current_user)
            db.session.commit()
            flash("Pubblicazione sospesa.", "success")
        except QuestionnaireError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))


@questionnaires_bp.post("/participant/questionnaires/<questionnaire_id>/start")
@participant_required
def participant_start(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    form = EmptyForm()
    if form.validate_on_submit():
        try:
            attempt = start_attempt(questionnaire, current_user)
            db.session.commit()
            return redirect(url_for("questionnaires.participant_attempt", attempt_id=attempt.id))
        except QuestionnaireError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return redirect(url_for("portal.dashboard"))


@questionnaires_bp.route("/participant/attempts/<attempt_id>", methods=["GET", "POST"])
@participant_required
def participant_attempt(attempt_id: str):
    attempt = db.get_or_404(QuestionnaireAttempt, attempt_id)
    if attempt.participant_user_id != current_user.id:
        return redirect(url_for("portal.dashboard"))
    if attempt.submitted_at is not None:
        return redirect(url_for("questionnaires.participant_result", attempt_id=attempt.id))
    form = AttemptSubmissionForm()
    if form.validate_on_submit():
        selections = {
            question.id: request.form.getlist(f"question_{question.id}")
            for question in attempt.questionnaire.questions
        }
        try:
            submit_attempt(attempt, selections)
            db.session.commit()
            return redirect(url_for("questionnaires.participant_result", attempt_id=attempt.id))
        except QuestionnaireError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("questionnaires/attempt.html", attempt=attempt, form=form)


@questionnaires_bp.get("/participant/attempts/<attempt_id>/result")
@participant_required
def participant_result(attempt_id: str):
    attempt = db.get_or_404(QuestionnaireAttempt, attempt_id)
    if attempt.participant_user_id != current_user.id or attempt.submitted_at is None:
        return redirect(url_for("portal.dashboard"))
    attempts = submitted_attempts(attempt.questionnaire, current_user)
    remaining = max(0, attempt.questionnaire.max_attempts - len(attempts))
    percentage = (attempt.score * 100 / attempt.maximum_score) if attempt.maximum_score else 0
    return render_template(
        "questionnaires/result.html",
        attempt=attempt,
        remaining=remaining,
        percentage=percentage,
        empty_form=EmptyForm(),
    )
