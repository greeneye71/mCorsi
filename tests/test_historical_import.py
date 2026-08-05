from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.worksheet.table import Table
from werkzeug.datastructures import FileStorage

from mcorsi.extensions import db
from mcorsi.models import Enrollment, ImportBatch, Role, User
from mcorsi.services.imports import confirm_batch, prepare_batch
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


def test_forms_history_is_deduplicated_and_imported(app):
    with app.app_context():
        admin = _admin()
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
        db.session.commit()
        assert batch.summary == {"source_responses": 4, "people": 2, "ready": 2}
        orietta = next(row for row in batch.rows if row.first_name == "Orietta")
        assert orietta.email == "orietta@example.it"
        assert orietta.source_rows == [3, 4, 5]
        assert "3 risposte consolidate" in orietta.warning

        confirm_batch(batch, actor=admin)
        db.session.commit()
        assert batch.status == "completed"
        assert batch.course.status == "completed"
        assert batch.course.first_session.starts_at.date() == date(2026, 6, 20)
        assert Enrollment.query.count() == 2
        assert all(item.attendance_status == "attended" for item in Enrollment.query.all())
        assert User.query.filter(User.roles.any(name="participant")).count() == 2
