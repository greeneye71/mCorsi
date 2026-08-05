from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.pdfgen import canvas
from werkzeug.datastructures import FileStorage

from mcorsi.extensions import db
from mcorsi.models import (
    AdmissionRequest,
    Certificate,
    CertificateTemplate,
    Course,
    Enrollment,
    Question,
    Questionnaire,
    QuestionOption,
    Role,
    User,
)
from mcorsi.services.certificates import inspect_template
from mcorsi.services.storage import path_for, save_upload


def _valid_pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 760, "Attestato end-to-end")
    document.showPage()
    document.save()
    return output.getvalue()


def test_complete_course_journey_from_otp_to_certificate(app, client, monkeypatch):
    participant_client = app.test_client()
    with app.app_context():
        admin = User(email="admin-e2e@example.it", profile_completed=True)
        admin.set_password("PasswordMoltoSicura1!")
        admin.roles.extend(
            [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    assert client.post(
        "/auth/login",
        data={"email": "admin-e2e@example.it", "password": "PasswordMoltoSicura1!"},
    ).status_code == 302
    created = client.post(
        "/courses/new",
        data={
            "title": "Sicurezza end-to-end",
            "description": "Corso di collaudo",
            "status": "open",
            "referent_user_id": admin_id,
            "session_date": "2026-07-10",
            "start_time": "09:00",
            "end_time": "13:00",
            "delivery_mode": "online",
            "meeting_url": "https://meet.example.test/aula",
            "certificate_validity_months": "60",
        },
    )
    assert created.status_code == 302
    with app.app_context():
        course = Course.query.filter_by(title="Sicurezza end-to-end").one()
        course_id, course_code = course.id, course.code

    assert participant_client.post(
        "/participant/access", data={"email": "partecipante-e2e@example.it"}
    ).status_code == 302
    code = re.search(r"\b(\d{6})\b", app.config["MAIL_OUTBOX"][-1]["text_body"]).group(1)
    assert participant_client.post("/participant/verify", data={"code": code}).status_code == 302
    profile = participant_client.post(
        "/participant/profile",
        data={
            "first_name": "Mario",
            "last_name": "Rossi",
            "birth_place": "Roma",
            "birth_date": "1980-05-10",
            "tax_code": "RSSMRA80E10H501Z",
            "mobile_phone": "+393331234567",
            "certificate_title": "Sig.",
            "company_country": "IT",
        },
    )
    assert profile.status_code == 302
    assert participant_client.post(
        "/participant/admissions", data={"code": course_code}
    ).status_code == 302

    with app.app_context():
        admission = AdmissionRequest.query.one()
        admission_id = admission.id
    assert client.post(
        f"/courses/{course_id}/admissions/{admission_id}/approve", data={}
    ).status_code == 302

    with app.app_context():
        course = db.session.get(Course, course_id)
        admin = db.session.get(User, admin_id)
        course.status = "in_progress"
        questionnaire = Questionnaire(
            course=course,
            title="Verifica finale",
            passing_percentage=70,
            max_attempts=3,
            sort_order=1,
            is_published=True,
        )
        question = Question(
            questionnaire=questionnaire,
            prompt="La formazione è obbligatoria?",
            response_type="single",
            sort_order=1,
        )
        correct = QuestionOption(
            question=question,
            text="Sì",
            is_correct=True,
            score_value=Decimal("10"),
            sort_order=1,
        )
        question.options.append(
            QuestionOption(text="No", is_correct=False, score_value=Decimal("0"), sort_order=2)
        )
        db.session.add_all([questionnaire, question, correct])
        db.session.commit()
        questionnaire_id, question_id, correct_id = questionnaire.id, question.id, correct.id

    started = participant_client.post(f"/participant/questionnaires/{questionnaire_id}/start", data={})
    assert started.status_code == 302
    attempt_url = started.headers["Location"]
    submitted = participant_client.post(
        attempt_url, data={f"question_{question_id}": correct_id}
    )
    assert submitted.status_code == 302

    with app.app_context():
        course = db.session.get(Course, course_id)
        admin = db.session.get(User, admin_id)
        course.status = "completed"
        enrollment = Enrollment.query.filter_by(course_id=course_id).one()
        enrollment_id = enrollment.id
        template_path = Path("mcorsi/assets/default_certificate.docx").resolve()
        stored = save_upload(
            FileStorage(
                stream=BytesIO(template_path.read_bytes()),
                filename="modello-e2e.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            actor=admin,
            category="templates",
        )
        course.certificate_template = CertificateTemplate(
            name="Modello E2E",
            stored_file=stored,
            placeholders=inspect_template(path_for(stored)),
            uploaded_by_user_id=admin.id,
        )
        db.session.commit()

    assert client.post(
        f"/documents/enrollments/{enrollment_id}/attendance",
        data={"attendance_status": "attended"},
    ).status_code == 302

    def fake_convert(_source, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "attestato.pdf"
        target.write_bytes(_valid_pdf())
        return target

    monkeypatch.setattr("mcorsi.services.certificates.convert_docx_to_pdf", fake_convert)
    generated = client.post(f"/documents/enrollments/{enrollment_id}/certificate", data={})
    assert generated.status_code == 302
    with app.app_context():
        certificate = Certificate.query.one()
        assert certificate.status == "valid"
        assert certificate.expires_at == date(2031, 7, 10)
        assert path_for(certificate.pdf_file).is_file()
    dashboard = participant_client.get("/participant")
    assert dashboard.status_code == 200
    assert b"Sicurezza end-to-end" in dashboard.data
    assert b"scadenza 07/2031" in dashboard.data
