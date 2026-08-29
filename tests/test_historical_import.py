from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.table import Table
from werkzeug.datastructures import FileStorage

from mcorsi.extensions import db
from mcorsi.models import Enrollment, ImportBatch, Role, User
from mcorsi.services.certificates import readiness
from mcorsi.services.imports import HistoricalImportError, confirm_batch, prepare_batch
from mcorsi.services.storage import save_upload


def _forms_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    headers = [
        "ID",
        "Ora di inizio",
        "Posta elettronica",
        "Titolo da riportare sull'attestato (sig. / dott. ecc....)",
        "Nome",
        "Nome2",
        "Cognome",
        "Email",
        "Luogo di nascita\n",
        "Data di nascita\n",
        "Una domanda del quiz",
    ]
    sheet.append(headers)
    sheet.append([1, datetime(2026, 6, 22, 15, 25), "anonymous", "Signora", None, "Antonella", "Locilento", "antonella@example.it", "Tricarico", datetime(1982, 2, 5), "Vero"])
    sheet.append([2, datetime(2026, 6, 24, 20, 31), "anonymous", "Signora", None, "Orietta", "Schiavi", "orietta@example.it", "Piacenza", datetime(1969, 5, 30), "Vero"])
    sheet.append([3, datetime(2026, 6, 24, 20, 47), "anonymous", "Signora", None, "Orietta", "Schiavi", "orietta@exampl.it", "Piacenza", datetime(1969, 5, 30), "Falso"])
    sheet.append([4, datetime(2026, 6, 24, 20, 57), "anonymous", "Signora", None, "Orietta", "Schiavi", "orietta@example.it", "Piacenza", datetime(1969, 5, 30), "Vero"])
    sheet.add_table(Table(displayName="Table1", ref="A1:K5"))
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _admin() -> User:
    user = User(email="admin@example.it", first_name="Ada", profile_completed=True)
    user.set_password("PasswordMoltoSicura1!")
    user.roles.extend(
        [Role.query.filter_by(name="admin").one(), Role.query.filter_by(name="operator").one()]
    )
    db.session.add(user)
    db.session.flush()
    return user


def _prepared_batch(admin: User) -> ImportBatch:
    stored = save_upload(
        FileStorage(
            stream=BytesIO(_forms_workbook()),
            filename="Corso radioprotezione 20_06_2026.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        actor=admin,
        category="imports",
    )
    batch = ImportBatch(
        stored_file=stored,
        course_title="Corso radioprotezione",
        course_date=date(2026, 6, 20),
        created_by_user_id=admin.id,
    )
    db.session.add(batch)
    prepare_batch(batch)
    return batch


def test_forms_history_is_deduplicated_and_imported(app):
    with app.app_context():
        admin = _admin()
        batch = _prepared_batch(admin)
        db.session.commit()
        assert batch.summary == {"source_responses": 4, "people": 2, "ready": 2}
        orietta = next(row for row in batch.rows if row.first_name == "Orietta")
        assert orietta.email == "orietta@example.it"
        assert orietta.source_rows == [3, 4, 5]
        assert "3 risposte consolidate" in orietta.warning

        confirm_batch(batch, actor=admin, attendance_status="pending")
        db.session.commit()
        assert batch.status == "completed"
        assert batch.course.status == "completed"
        assert batch.course.is_historical is True
        assert batch.course.first_session.starts_at.date() == date(2026, 6, 20)
        assert Enrollment.query.count() == 2
        assert batch.summary["attendance_status"] == "pending"
        assert all(item.attendance_status == "pending" for item in Enrollment.query.all())
        assert all(
            readiness(item)[1]
            == ["presenza non confermata", "modello attestato non assegnato"]
            for item in Enrollment.query.all()
        )
        batch.course.is_historical = False
        assert readiness(Enrollment.query.first())[1] == [
            "presenza non confermata",
            "questionari non superati",
            "modello attestato non assegnato",
        ]
        assert User.query.filter(User.roles.any(name="participant")).count() == 2


def test_preview_shows_attendance_choice_and_applies_it(app, client):
    with app.app_context():
        admin = _admin()
        batch = _prepared_batch(admin)
        db.session.commit()
        batch_id = batch.id

    assert client.post(
        "/auth/login",
        data={"email": "admin@example.it", "password": "PasswordMoltoSicura1!"},
    ).status_code == 302

    preview = client.get(f"/imports/{batch_id}")
    assert preview.status_code == 200
    assert b'name="attendance_status"' in preview.data
    assert b'<option selected value="pending">Da confermare</option>' in preview.data
    assert b"Da confermare" in preview.data
    assert b"Presenti" in preview.data
    assert b"Assenti" in preview.data

    confirmed = client.post(
        f"/imports/{batch_id}/confirm",
        data={"attendance_status": "attended"},
    )
    assert confirmed.status_code == 302
    with app.app_context():
        batch = db.session.get(ImportBatch, batch_id)
        assert batch.summary["attendance_status"] == "attended"
        assert all(item.attendance_status == "attended" for item in Enrollment.query.all())


def test_confirm_batch_rejects_an_invalid_attendance_status(app):
    with app.app_context():
        admin = _admin()
        batch = _prepared_batch(admin)

        with pytest.raises(HistoricalImportError, match="stato delle presenze"):
            confirm_batch(batch, actor=admin, attendance_status="unknown")

        assert batch.course is None
        assert Enrollment.query.count() == 0
