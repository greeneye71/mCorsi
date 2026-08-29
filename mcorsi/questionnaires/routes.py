from __future__ import annotations

import json
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Course, Question, Questionnaire, QuestionnaireAttempt
from ..services.audit import record_event
from ..services.permissions import participant_required, staff_required
from ..services.questionnaire_transfer import (
    QuestionnaireTransferError,
    duplicate_questionnaire,
    import_questionnaire,
    questionnaire_to_dict,
    questionnaire_to_markdown,
)
from ..services.questionnaires import (
    QuestionnaireError,
    attempts_used,
    ensure_draft_editable,
    expire_attempt,
    expire_open_attempts,
    publish_questionnaire,
    replace_question_options,
    start_attempt,
    submit_attempt,
    unpublish_questionnaire,
    validation_errors,
)
from .forms import (
    AttemptSubmissionForm,
    EmptyForm,
    QuestionForm,
    QuestionnaireCourseForm,
    QuestionnaireDuplicateForm,
    QuestionnaireForm,
    QuestionnaireImportForm,
)


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


def _course_choices() -> list[tuple[str, str]]:
    courses = Course.query.order_by(Course.title, Course.created_at.desc()).all()
    return [(course.id, f"{course.title} · {course.code}") for course in courses]


@questionnaires_bp.get("/questionnaires")
@staff_required
def index():
    status = request.args.get("status", "all")
    course_id = request.args.get("course_id", "")
    query = Questionnaire.query
    if status == "published":
        query = query.filter(Questionnaire.is_published.is_(True))
    elif status == "draft":
        query = query.filter(Questionnaire.is_published.is_(False))
    else:
        status = "all"
    if course_id:
        query = query.filter_by(course_id=course_id)
    questionnaires = query.order_by(Questionnaire.updated_at.desc()).all()
    choices = _course_choices()
    create_form = QuestionnaireCourseForm(prefix="create")
    create_form.course_id.choices = choices
    import_form = QuestionnaireImportForm(prefix="import")
    import_form.course_id.choices = choices
    return render_template(
        "questionnaires/index.html",
        questionnaires=questionnaires,
        courses=Course.query.order_by(Course.title).all(),
        selected_course_id=course_id,
        selected_status=status,
        create_form=create_form,
        import_form=import_form,
    )


@questionnaires_bp.post("/questionnaires/new")
@staff_required
def create_from_archive():
    form = QuestionnaireCourseForm(prefix="create")
    form.course_id.choices = _course_choices()
    if form.validate_on_submit():
        return redirect(url_for("questionnaires.create", course_id=form.course_id.data))
    flash("Seleziona un corso valido.", "error")
    return redirect(url_for("questionnaires.index"))


@questionnaires_bp.post("/questionnaires/import")
@staff_required
def import_json():
    form = QuestionnaireImportForm(prefix="import")
    form.course_id.choices = _course_choices()
    if not form.validate_on_submit():
        flash("Seleziona un corso e un file JSON valido.", "error")
        return redirect(url_for("questionnaires.index"))
    raw = form.file.data.read(1_048_577)
    if len(raw) > 1_048_576:
        flash("Il file JSON supera il limite di 1 MB.", "error")
        return redirect(url_for("questionnaires.index"))
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        course = db.get_or_404(Course, form.course_id.data)
        questionnaire = import_questionnaire(payload, course=course, actor=current_user)
        db.session.commit()
    except (UnicodeDecodeError, json.JSONDecodeError, QuestionnaireTransferError) as exc:
        db.session.rollback()
        flash(f"Importazione non riuscita: {exc}", "error")
        return redirect(url_for("questionnaires.index"))
    flash("Questionario importato come bozza. Controllalo prima di pubblicarlo.", "success")
    return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))


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


@questionnaires_bp.get("/questionnaires/<questionnaire_id>/preview")
@staff_required
def preview(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    return render_template("questionnaires/preview.html", questionnaire=questionnaire)


@questionnaires_bp.route("/questionnaires/<questionnaire_id>/duplicate", methods=["GET", "POST"])
@staff_required
def duplicate(questionnaire_id: str):
    source = db.get_or_404(Questionnaire, questionnaire_id)
    form = QuestionnaireDuplicateForm()
    form.course_id.choices = _course_choices()
    if not form.is_submitted():
        form.course_id.data = source.course_id
    if form.validate_on_submit():
        target_course = db.get_or_404(Course, form.course_id.data)
        try:
            questionnaire = duplicate_questionnaire(source, course=target_course, actor=current_user)
            db.session.commit()
        except QuestionnaireTransferError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        else:
            flash("Questionario duplicato come bozza indipendente.", "success")
            return redirect(url_for("questionnaires.detail", questionnaire_id=questionnaire.id))
    return render_template("questionnaires/duplicate.html", questionnaire=source, form=form)


def _download_name(questionnaire: Questionnaire, suffix: str) -> str:
    stem = secure_filename(questionnaire.title).strip("._") or "questionario"
    return f"{stem}.{suffix}"


@questionnaires_bp.get("/questionnaires/<questionnaire_id>/export.json")
@staff_required
def export_json(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    content = json.dumps(
        questionnaire_to_dict(questionnaire), ensure_ascii=False, indent=2
    ).encode("utf-8") + b"\n"
    return send_file(
        BytesIO(content),
        as_attachment=True,
        download_name=_download_name(questionnaire, "questionario.json"),
        mimetype="application/json",
    )


@questionnaires_bp.get("/questionnaires/<questionnaire_id>/export.md")
@staff_required
def export_markdown(questionnaire_id: str):
    questionnaire = db.get_or_404(Questionnaire, questionnaire_id)
    return send_file(
        BytesIO(questionnaire_to_markdown(questionnaire).encode("utf-8")),
        as_attachment=True,
        download_name=_download_name(questionnaire, "questionario.md"),
        mimetype="text/markdown",
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
            if expire_open_attempts(questionnaire, current_user):
                db.session.commit()
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
    if attempt.is_expired:
        expire_attempt(attempt)
        db.session.commit()
        flash("Il tentativo è scaduto e non può più essere inviato.", "error")
        return redirect(url_for("portal.dashboard"))
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
    remaining = max(
        0,
        attempt.questionnaire.max_attempts
        - attempts_used(attempt.questionnaire, current_user),
    )
    percentage = (attempt.score * 100 / attempt.maximum_score) if attempt.maximum_score else 0
    return render_template(
        "questionnaires/result.html",
        attempt=attempt,
        remaining=remaining,
        percentage=percentage,
        empty_form=EmptyForm(),
    )
