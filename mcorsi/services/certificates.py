from __future__ import annotations

import shutil
import subprocess
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm
from flask import current_app
from pypdf import PdfReader
from PIL import Image

from ..extensions import db
from ..models import (
    Certificate,
    CertificateTemplate,
    Course,
    Enrollment,
    SignatureAsset,
    User,
)
from .questionnaires import course_assessment_complete
from .storage import path_for, save_bytes, storage_root


ALLOWED_PLACEHOLDERS = {
    "participant_first_name",
    "participant_last_name",
    "participant_full_name",
    "birth_place",
    "birth_date",
    "tax_code",
    "course_title",
    "course_legal_references",
    "course_topics",
    "course_date",
    "course_code",
    "certificate_number",
    "issue_date",
    "expiry_date",
    "company_name",
    "company_vat",
    "signer_name",
    "signer_title",
    "signature_image",
}


class CertificateError(ValueError):
    pass


def validate_signature_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width < 100 or image.height < 40:
                raise CertificateError("L'immagine della firma è troppo piccola.")
    except CertificateError:
        raise
    except Exception as exc:
        raise CertificateError("Il file non contiene un'immagine di firma valida.") from exc


def inspect_template(path: Path) -> list[str]:
    try:
        variables = set(DocxTemplate(str(path)).get_undeclared_template_variables())
    except Exception as exc:
        raise CertificateError("Il documento DOCX non è un modello valido.") from exc
    unknown = sorted(variables - ALLOWED_PLACEHOLDERS)
    if unknown:
        raise CertificateError("Campi non riconosciuti: " + ", ".join(unknown))
    if "course_title" not in variables:
        raise CertificateError("Il modello deve contenere {{ course_title }}.")
    has_name = "participant_full_name" in variables or {
        "participant_first_name",
        "participant_last_name",
    }.issubset(variables)
    if not has_name:
        raise CertificateError(
            "Il modello deve contenere {{ participant_full_name }} oppure nome e cognome separati."
        )
    return sorted(variables)


def find_libreoffice() -> str | None:
    configured = current_app.config.get("LIBREOFFICE_PATH", "")
    candidates = [
        configured,
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def converter_status() -> tuple[bool, str]:
    executable = find_libreoffice()
    if executable:
        return True, executable
    return False, "LibreOffice non trovato; installalo o configura MCORSI_LIBREOFFICE_PATH."


def convert_docx_to_pdf(docx_path: Path, output_dir: Path) -> Path:
    executable = find_libreoffice()
    if not executable:
        raise CertificateError(
            "Generazione PDF non disponibile: installa LibreOffice o configura MCORSI_LIBREOFFICE_PATH."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = output_dir / f"lo-profile-{uuid4().hex}"
    profile.mkdir()
    profile_uri = profile.resolve().as_uri()
    command = [
        executable,
        "--headless",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(docx_path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=90, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CertificateError("LibreOffice non ha completato la conversione PDF.") from exc
    pdf_path = output_dir / f"{docx_path.stem}.pdf"
    if completed.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout or "errore sconosciuto").strip()
        raise CertificateError(f"Conversione PDF non riuscita: {detail[:300]}")
    try:
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            raise ValueError
    except Exception as exc:
        raise CertificateError("Il PDF generato non è valido.") from exc
    return pdf_path


def add_months(day: date, months: int | None) -> date | None:
    if not months:
        return None
    target = day.month - 1 + months
    year = day.year + target // 12
    month = target % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def course_date(course: Course) -> date:
    if not course.first_session:
        raise CertificateError("Il corso non ha una data di svolgimento.")
    value = course.first_session.starts_at
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(course.timezone_name or "Europe/Rome")).date()


def readiness(enrollment: Enrollment) -> tuple[bool, list[str]]:
    reasons = []
    if enrollment.course.status != "completed":
        reasons.append("corso non concluso")
    if enrollment.attendance_status != "attended":
        reasons.append("presenza non confermata")
    profile = enrollment.participant.participant_profile
    if not enrollment.participant.profile_completed or not profile:
        reasons.append("anagrafica incompleta")
    if (
        not enrollment.course.is_historical
        and not course_assessment_complete(enrollment.course, enrollment.participant)
    ):
        reasons.append("questionari non superati")
    if not enrollment.course.certificate_template:
        reasons.append("modello attestato non assegnato")
    return not reasons, reasons


def _context(enrollment: Enrollment, number: str, issued: date, expiry: date | None) -> dict:
    participant = enrollment.participant
    profile = participant.participant_profile
    employment = profile.current_employment if profile else None
    company = employment.company if employment else None
    signature = enrollment.course.signature_asset
    return {
        "participant_first_name": participant.first_name,
        "participant_last_name": participant.last_name,
        "participant_full_name": participant.display_name,
        "birth_place": profile.birth_place if profile else "",
        "birth_date": profile.birth_date.strftime("%d/%m/%Y") if profile and profile.birth_date else "",
        "tax_code": profile.tax_code if profile else "",
        "course_title": enrollment.course.title,
        "course_legal_references": enrollment.course.legal_references,
        "course_topics": enrollment.course.topics,
        "course_date": course_date(enrollment.course).strftime("%d/%m/%Y"),
        "course_code": enrollment.course.code,
        "certificate_number": number,
        "issue_date": issued.strftime("%d/%m/%Y"),
        "expiry_date": expiry.strftime("%d/%m/%Y") if expiry else "Nessuna scadenza",
        "company_name": company.business_name if company else "",
        "company_vat": company.vat_number if company else "",
        "signer_name": signature.signer_name if signature else "",
        "signer_title": signature.signer_title if signature else "",
    }


def generate_certificate(enrollment: Enrollment, *, actor: User) -> Certificate:
    if enrollment.certificate:
        raise CertificateError("Per questa iscrizione esiste già un attestato.")
    ready, reasons = readiness(enrollment)
    if not ready:
        raise CertificateError("Attestato non generabile: " + ", ".join(reasons) + ".")
    course = enrollment.course
    template = course.certificate_template
    number = f"MC-{course_date(course).year}-{uuid4().hex[:10].upper()}"
    issued = datetime.now(timezone.utc)
    expiry = add_months(course_date(course), course.certificate_validity_months)
    context = _context(enrollment, number, issued.date(), expiry)
    profile = enrollment.participant.participant_profile
    employment = profile.current_employment if profile else None

    work_root = storage_root() / ".work"
    work_root.mkdir(parents=True, exist_ok=True)
    temp_dir = (work_root / f"mcorsi-cert-{uuid4().hex}").resolve()
    if work_root.resolve() not in temp_dir.parents:
        raise CertificateError("Percorso temporaneo non valido.")
    temp_dir.mkdir()
    try:
        rendered_docx = temp_dir / "attestato.docx"
        document = DocxTemplate(str(path_for(template.stored_file)))
        if course.signature_asset and "signature_image" in template.placeholders:
            context["signature_image"] = InlineImage(
                document, str(path_for(course.signature_asset.stored_file)), width=Mm(38)
            )
        else:
            context["signature_image"] = ""
        try:
            document.render(context, autoescape=True)
            document.save(str(rendered_docx))
        except Exception as exc:
            raise CertificateError("Impossibile compilare il modello DOCX.") from exc
        pdf_path = convert_docx_to_pdf(rendered_docx, temp_dir / "pdf")
        pdf_file = save_bytes(
            pdf_path.read_bytes(),
            filename=f"attestato-{course.code}-{participant_slug(enrollment.participant)}.pdf",
            mime_type="application/pdf",
            actor=actor,
            category="certificates",
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    certificate = Certificate(
        course=course,
        participant_user_id=enrollment.participant_user_id,
        company_id=employment.company_id if employment else None,
        enrollment=enrollment,
        pdf_file=pdf_file,
        template=template,
        certificate_number=number,
        title_snapshot=course.title,
        course_date=course_date(course),
        issued_at=issued,
        expires_at=expiry,
        source="generated",
        verification_status="verified",
        status="valid",
        data_snapshot={key: str(value) for key, value in context.items() if key != "signature_image"},
        generated_by_user_id=actor.id,
    )
    db.session.add(certificate)
    db.session.flush()
    return certificate


def participant_slug(participant: User) -> str:
    value = f"{participant.last_name}-{participant.first_name}".strip("-").casefold()
    safe = "".join(char if char.isalnum() else "-" for char in value)
    return "-".join(filter(None, safe.split("-"))) or participant.id[:8]


def validate_pdf(path: Path) -> None:
    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            raise ValueError
    except Exception as exc:
        raise CertificateError("Il file caricato non è un PDF valido.") from exc
