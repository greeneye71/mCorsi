"""Riproduzioni non distruttive: usa esclusivamente database nuovi sotto instance.

Esecuzione dalla radice: instance/lock-venv/Scripts/python.exe docs/audit-2026-10-10/reproduce.py
Le assert descrivono i difetti della revisione esaminata, non il comportamento desiderato.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docx import Document
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from starlette.testclient import TestClient
from werkzeug.utils import safe_join

from mcorsi import create_app
from mcorsi.cli import ensure_roles
from mcorsi.extensions import db
from mcorsi.mcp_server import create_mcp_server
from mcorsi.models import (
    Certificate, Company, CompanyContact, Course, EmailOutbox, ImportBatch,
    ImportRow, NotificationConfiguration, OneTimeCode, Role, StoredFile, User,
)
from mcorsi.services import notifications, otp
from mcorsi.services.backup import create_backup, restore_backup, verify_backup
from mcorsi.services.imports import confirm_batch
from mcorsi.services.mcp_access import create_access_token, verify_access_token
from mcorsi.services.mcp_tools import list_courses_data

PASSWORD = "Audit-Only-2026!"


def application():
    folder = ROOT / "instance" / "audit-20261010" / uuid4().hex
    app = create_app("testing", {
        "SECRET_KEY": "audit-only-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(folder / 'test.sqlite3').as_posix()}",
        "PRIVATE_STORAGE_PATH": str(folder / "storage"),
        "BACKUP_PATH": str(folder / "backups"),
        "MAIL_OUTBOX": [],
        "MCP_ALLOWED_HOSTS": "testserver",
    })
    with app.app_context():
        db.create_all()
        ensure_roles()
        db.session.commit()
    return app


def user(email, *roles):
    item = User(email=email, profile_completed=True)
    item.roles.extend(Role.query.filter_by(name=role).one() for role in roles)
    if "admin" in roles or "operator" in roles:
        item.set_password(PASSWORD)
    db.session.add(item)
    db.session.commit()
    return item


def password_session():
    app = application()
    with app.app_context():
        account_id = user("staff@example.org", "admin", "operator").id
    client = app.test_client()
    assert client.post("/auth/login", data={"email": "staff@example.org", "password": PASSWORD, "remember": "y"}).status_code == 302
    cookie = client.get_cookie("remember_token")
    with app.app_context():
        db.session.get(User, account_id).set_password("Changed-Audit-2026!")
        db.session.commit()
    after_reset = client.get("/settings/").status_code
    restored = app.test_client()
    restored.set_cookie("remember_token", cookie.value)
    remember_after_reset = restored.get("/settings/").status_code
    with app.app_context():
        db.session.get(User, account_id).is_active = False
        db.session.commit()
    while_disabled = restored.get("/settings/").status_code
    with app.app_context():
        db.session.get(User, account_id).is_active = True
        db.session.commit()
    after_reenable = restored.get("/settings/").status_code
    assert (after_reset, remember_after_reset, while_disabled, after_reenable) == (200, 200, 302, 200)
    return dict(after_password_reset=after_reset, old_remember_cookie=remember_after_reset,
                while_disabled=while_disabled, old_cookie_after_reenable=after_reenable)


def mcp_disabled_owner():
    app = application()
    with app.app_context():
        owner = user("mcp@example.org", "admin", "operator")
        raw, access = create_access_token(name="audit", scopes=["courses:read"], creator=owner, expires_at=None)
        db.session.commit()
        owner.is_active = False
        db.session.commit()
        accepted = verify_access_token(raw, update_last_used=False) is not None
    server = create_mcp_server(app)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_courses", "arguments": {}}}
    with TestClient(server.streamable_http_app()) as client:
        response = client.post("/mcp", json=payload, headers={"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {raw}"})
    body = response.json()
    assert accepted and response.status_code == 200 and not body["result"].get("isError")
    return dict(token_accepted=accepted, http=response.status_code, tool_error=body["result"].get("isError", False))


def concurrent_otp(valid):
    app = application()
    with app.app_context():
        participant = user("otp@example.org", "participant")
        challenge = otp.request_participant_code(participant.email, "127.0.0.1")
        challenge_id = challenge.id
        sent = re.search(r"\b\d{6}\b", app.config["MAIL_OUTBOX"][-1]["text_body"]).group()
    barrier = threading.Barrier(2)
    original = otp._hash_code
    def synchronized_hash(*args):
        barrier.wait(timeout=10)
        return original(*args)
    submitted = sent if valid else ("000000" if sent != "000000" else "111111")
    def verify():
        with app.app_context():
            try:
                otp.verify_participant_code(challenge_id, submitted)
                return "success"
            except otp.OtpError:
                return "OtpError"
    with patch.object(otp, "_hash_code", synchronized_hash):
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: verify(), range(2)))
    with app.app_context():
        count = db.session.get(OneTimeCode, challenge_id).attempts
    assert outcomes == (["success", "success"] if valid else ["OtpError", "OtpError"])
    assert count == 1
    return dict(valid_code=valid, outcomes=outcomes, persisted_attempts=count)


def inactive_primary_contact():
    app = application()
    with app.app_context():
        account = user("company@example.org", "company_contact")
        company = Company(business_name="Audit", vat_number="12345678901", address="Via Audit 1", postal_code="00100", city="Roma", email=account.email, verification_status="verified")
        db.session.add(company)
        db.session.flush()
        db.session.add(CompanyContact(company=company, user=account, is_active=False))
        db.session.commit()
        try:
            otp.request_company_code(account.email, company.vat_number)
        except IntegrityError:
            db.session.rollback()
            return dict(error="IntegrityError", cause="uq_company_contact_user")
    raise AssertionError("Difetto non riprodotto")


def mixed_portal_roles():
    app = application()
    with app.app_context():
        account = user("both@example.org", "participant", "company_contact")
        challenge = otp.request_participant_code(account.email)
        code = re.search(r"\b\d{6}\b", app.config["MAIL_OUTBOX"][-1]["text_body"]).group()
        challenge_id = challenge.id
    client = app.test_client()
    with client.session_transaction() as session:
        session["otp_challenge_id"] = challenge_id
    assert client.post("/participant/verify", data={"code": code}).status_code == 302
    home = client.get("/")
    landing = client.get(home.location).status_code
    assert home.location.endswith("/company") and landing == 403
    return dict(home_location=home.location, destination_status=landing)


def orphan_file():
    app = application()
    with app.app_context():
        admin = user("upload@example.org", "admin", "operator")
        account_id = admin.id
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = account_id
        session["_fresh"] = True
    document = Document()
    document.add_paragraph("DOCX valido ma senza i segnaposto richiesti")
    data = io.BytesIO()
    document.save(data)
    data.seek(0)
    response = client.post("/documents/templates", data={"name": "audit", "file": (data, "invalid-template.docx")})
    with app.app_context():
        count = StoredFile.query.count()
    files = list(Path(app.config["PRIVATE_STORAGE_PATH"]).rglob("*.docx"))
    assert response.status_code == 302 and count == 0 and len(files) == 1
    return dict(stored_file_rows=count, orphan_files=len(files))


def concurrent_delivery():
    app = application()
    with app.app_context():
        db.session.add(EmailOutbox(message_type="audit", recipient_email="audit@example.org", subject="Audit", text_body="Audit"))
        db.session.commit()
    barrier = threading.Barrier(2)
    deliveries = []
    def fake_mail(**kwargs):
        deliveries.append(kwargs["recipient"])
        barrier.wait(timeout=10)
    def deliver():
        with app.app_context():
            return notifications.deliver_pending()
    with patch.object(notifications, "send_email", fake_mail):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: deliver(), range(2)))
    assert len(deliveries) == 2 and sum(r["sent"] for r in results) == 2
    return dict(queue_rows=1, actual_deliveries=len(deliveries), workers=results)


def unverified_company_notification():
    app = application()
    with app.app_context():
        admin = user("owner@example.org", "admin", "operator")
        participant = user("person@example.org", "participant")
        company = Company(business_name="Audit", vat_number="12345678901", address="Via Audit 1", postal_code="00100", city="Roma", email="unverified@example.org", verification_status="rejected")
        file = StoredFile(storage_key="audit.pdf", original_name="audit.pdf", mime_type="application/pdf", size_bytes=1, sha256="0" * 64, uploaded_by_user_id=admin.id)
        db.session.add_all([company, file])
        db.session.flush()
        certificate = Certificate(participant_user_id=participant.id, company=company, pdf_file=file, title_snapshot="Audit", course_date=date.today(), expires_at=date.today() + timedelta(days=30), source="participant_upload", verification_status="verified")
        db.session.add_all([certificate, NotificationConfiguration(id=1, updated_by_user_id=admin.id)])
        db.session.commit()
        counts = notifications.enqueue_reminders()
        companies = EmailOutbox.query.filter_by(message_type="certificate_expiry_company").all()
        assert counts["certificate_company"] == 1 and companies[0].recipient_email == "unverified@example.org"
        return dict(company_status=company.verification_status, company_messages=len(companies), recipient=companies[0].recipient_email)


def incomplete_backup():
    app = application()
    path = Path(app.config["BACKUP_PATH"]) / "invalid.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format_version": 1, "files": []}))
    with app.app_context():
        manifest = verify_backup(path, allow_legacy_unencrypted=True)
    assert manifest["files"] == []
    return dict(verify_accepted=True, database_present=False)


def upcoming_limit():
    app = application()
    from mcorsi.models import CourseSession
    with app.app_context():
        admin = user("courses@example.org", "admin", "operator")
        now = datetime.now(timezone.utc)
        for i, delta in enumerate((10, -10)):
            course = Course(title=f"Audit {i}", code=f"AUDIT{i}", creator_user_id=admin.id, referent_user_id=admin.id, created_at=now + timedelta(seconds=i))
            start = now + timedelta(days=delta)
            course.sessions.append(CourseSession(sequence=1, title="Audit", starts_at=start, ends_at=start + timedelta(hours=1)))
            db.session.add(course)
        db.session.commit()
        result = list_courses_data(upcoming_only=True, limit=1)
        assert result["count"] == 0
        return dict(future_courses_in_database=1, returned_count=result["count"], limit=1)


def broken_import_transaction():
    app = application()
    with app.app_context():
        admin = user("import@example.org", "admin", "operator")
        stored = StoredFile(storage_key="audit.xlsx", original_name="audit.xlsx", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", size_bytes=1, sha256="0" * 64, uploaded_by_user_id=admin.id)
        batch = ImportBatch(stored_file=stored, course_title="Audit", course_date=date.today(), created_by_user_id=admin.id)
        batch.rows.append(ImportRow(row_number=1, email="invalid@example.org", first_name="Audit", last_name="Audit", status="ready"))
        db.session.add(batch)
        db.session.commit()
        def invalid_participant(_row):
            # Simula un conflitto d'integrita' durante il flush, senza modificare il codice.
            db.session.add(User(email=admin.email))
            db.session.flush()
        with patch("mcorsi.services.imports._find_participant", invalid_participant):
            try:
                confirm_batch(batch, actor=admin, attendance_status="pending")
            except PendingRollbackError:
                db.session.rollback()
                return dict(error="PendingRollbackError", original_error="IntegrityError", scope="fault injection")
    raise AssertionError("Difetto non riprodotto")


def last_attempt_resume():
    app = application()
    from mcorsi.models import AdmissionRequest, Enrollment, ParticipantProfile, Questionnaire, QuestionnaireAttempt
    with app.app_context():
        admin = user("resume-admin@example.org", "admin", "operator")
        participant = user("resume@example.org", "participant")
        participant.participant_profile = ParticipantProfile()
        participant_id = participant.id
        course = Course(title="Audit", code="RESUME", status="open", creator_user_id=admin.id, referent_user_id=admin.id)
        admission = AdmissionRequest(course=course, participant=participant, status="approved")
        db.session.add_all([course, admission, Enrollment(course=course, participant=participant, admission_request=admission)])
        questionnaire = Questionnaire(course=course, title="Audit", is_published=True, max_attempts=3)
        db.session.add(questionnaire)
        db.session.flush()
        now = datetime.now(timezone.utc)
        for number in (1, 2):
            db.session.add(QuestionnaireAttempt(questionnaire=questionnaire, participant=participant, attempt_number=number, passing_percentage_snapshot=70, expires_at=now-timedelta(hours=2), expired_at=now-timedelta(hours=1), open_slot=None))
        db.session.add(QuestionnaireAttempt(questionnaire=questionnaire, participant=participant, attempt_number=3, passing_percentage_snapshot=70, expires_at=now+timedelta(hours=1), open_slot=True))
        db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = participant_id
        session["_fresh"] = True
    response = client.get("/participant")
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and "Tentativi esauriti" in html and "/start" not in html
    return dict(open_attempt_number=3, dashboard_says_exhausted=True, resume_action_present=False)


def restore_storage_failure():
    app = application()
    app.config["BACKUP_ENCRYPTION_KEY"] = "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
    storage = Path(app.config["PRIVATE_STORAGE_PATH"])
    (storage / "sentinel.txt").write_text("Audit", encoding="utf-8")
    with app.app_context():
        user("restore@example.org", "admin", "operator")
        archive = create_backup()
        original_replace = Path.replace
        def fail_new_storage(path, target):
            if path.name.startswith(".storage.restore-"):
                raise PermissionError("Errore simulato sul secondo rename")
            return original_replace(path, target)
        with patch.object(Path, "replace", fail_new_storage):
            try:
                restore_backup(archive, safety_backup=False)
            except PermissionError:
                pass
            else:
                raise AssertionError("Errore atteso")
    previous = list(storage.parent.glob(".storage.before-restore-*"))
    assert not storage.exists() and len(previous) == 1
    return dict(configured_storage_exists=storage.exists(), previous_storage_preserved=len(previous), scope="fault injection")


def company_html_email():
    app = application()
    with app.app_context():
        company = Company(business_name='<a href="https://example.org/audit">Test</a>', vat_number="12345678901", address="Via Audit 1", postal_code="00100", city="Roma", email="html@example.org", verification_status="verified")
        db.session.add(company)
        db.session.commit()
        otp.request_company_code(company.email, company.vat_number)
        body = app.config["MAIL_OUTBOX"][-1]["html_body"]
        assert '<a href="https://example.org/audit">Test</a>' in body
    return dict(unescaped_html_in_email=True)


def creation_audit_id():
    app = application()
    from datetime import time
    from mcorsi.models import AuditLog
    from mcorsi.services.courses import create_course
    with app.app_context():
        admin = user("audit-log@example.org", "admin", "operator")
        course = create_course(actor=admin, data={"title": "Audit", "status": "draft", "referent_user_id": admin.id, "session_date": date.today(), "start_time": time(9), "end_time": time(10), "delivery_mode": "online"})
        db.session.commit()
        entry = AuditLog.query.filter_by(event_type="course.created").one()
        assert course.id and entry.target_id == "None"
    return dict(entity_id_exists=True, audit_target_id=entry.target_id)


def main():
    checks = {
        "S01_password_session": password_session,
        "S02_mcp_disabled_owner": mcp_disabled_owner,
        "S03_otp_reuse": lambda: concurrent_otp(True),
        "S03_otp_lost_attempt": lambda: concurrent_otp(False),
        "B01_inactive_primary_contact": inactive_primary_contact,
        "B02_mixed_portal_roles": mixed_portal_roles,
        "S04_orphan_file": orphan_file,
        "B03_duplicate_delivery": concurrent_delivery,
        "S05_unverified_company_notification": unverified_company_notification,
        "B04_incomplete_backup": incomplete_backup,
        "B05_upcoming_limit": upcoming_limit,
        "B06_import_transaction": broken_import_transaction,
        "B08_last_attempt_resume": last_attempt_resume,
        "B09_restore_storage_failure": restore_storage_failure,
        "S07_company_html_email": company_html_email,
        "B10_creation_audit_id": creation_audit_id,
    }
    results = {name: check() for name, check in checks.items()}
    results["D03_werkzeug_safe_join_primitive"] = {"result": safe_join("C:/static", "NUL:")}
    output = ROOT / "instance" / "audit-20261010" / "reproductions.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
