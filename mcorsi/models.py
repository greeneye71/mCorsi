from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


def normalize_email(value: str) -> str:
    return value.strip().casefold()


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    email = db.Column(db.String(320), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(512), nullable=True)
    first_name = db.Column(db.String(120), nullable=False, default="")
    last_name = db.Column(db.String(120), nullable=False, default="")
    mobile_phone = db.Column(db.String(32), nullable=False, default="")
    mobile_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    profile_completed = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    roles = db.relationship("Role", secondary=user_roles, lazy="selectin")
    participant_profile = db.relationship(
        "ParticipantProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_email(self, value: str) -> None:
        self.email = normalize_email(value)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    def has_role(self, *names: str) -> bool:
        allowed = set(names)
        return any(role.name in allowed for role in self.roles)

    @property
    def display_name(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    actor_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type = db.Column(db.String(100), nullable=False, index=True)
    target_type = db.Column(db.String(80), nullable=False, default="")
    target_id = db.Column(db.String(80), nullable=False, default="")
    detail = db.Column(db.JSON, nullable=False, default=dict)
    ip_address = db.Column(db.String(64), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    actor = db.relationship("User")


class SystemVersion(db.Model):
    __tablename__ = "system_version"

    id = db.Column(db.Integer, primary_key=True, default=1)
    application_version = db.Column(db.String(32), nullable=False)
    database_version = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class McpAccessToken(db.Model):
    __tablename__ = "mcp_access_tokens"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(160), nullable=False)
    token_prefix = db.Column(db.String(24), unique=True, nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    scopes = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    created_by = db.relationship("User")


class SmtpConfiguration(db.Model):
    __tablename__ = "smtp_configurations"

    id = db.Column(db.Integer, primary_key=True, default=1)
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=587)
    username = db.Column(db.String(320), nullable=False, default="")
    password_encrypted = db.Column(db.Text, nullable=False, default="")
    from_email = db.Column(db.String(320), nullable=False)
    from_name = db.Column(db.String(160), nullable=False, default="mCorsi")
    use_starttls = db.Column(db.Boolean, nullable=False, default=True)
    use_ssl = db.Column(db.Boolean, nullable=False, default=False)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=20)
    updated_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    updated_by = db.relationship("User")


class NotificationConfiguration(db.Model):
    __tablename__ = "notification_configurations"

    id = db.Column(db.Integer, primary_key=True, default=1)
    course_reminders_enabled = db.Column(db.Boolean, nullable=False, default=True)
    course_reminder_days = db.Column(db.Integer, nullable=False, default=3)
    certificate_reminders_enabled = db.Column(db.Boolean, nullable=False, default=True)
    certificate_expiry_days = db.Column(db.Integer, nullable=False, default=180)
    updated_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    updated_by = db.relationship("User")


class EmailOutbox(db.Model):
    __tablename__ = "email_outbox"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    message_type = db.Column(db.String(50), nullable=False, index=True)
    recipient_email = db.Column(db.String(320), nullable=False, index=True)
    subject = db.Column(db.String(300), nullable=False)
    text_body = db.Column(db.Text, nullable=False)
    html_body = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    last_error = db.Column(db.Text, nullable=False, default="")
    related_type = db.Column(db.String(50), nullable=False, default="")
    related_id = db.Column(db.String(80), nullable=False, default="")
    unique_key = db.Column(db.String(255), nullable=True, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)


class OneTimeCode(db.Model):
    __tablename__ = "one_time_codes"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose = db.Column(db.String(40), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    requested_ip = db.Column(db.String(64), nullable=False, default="", index=True)
    context = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    user = db.relationship("User")


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    business_name = db.Column(db.String(240), nullable=False, index=True)
    vat_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    tax_code = db.Column(db.String(32), nullable=False, default="")
    address = db.Column(db.String(240), nullable=False)
    postal_code = db.Column(db.String(16), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    province = db.Column(db.String(8), nullable=False, default="")
    country = db.Column(db.String(2), nullable=False, default="IT")
    email = db.Column(db.String(320), nullable=False)
    pec = db.Column(db.String(320), nullable=False, default="")
    verification_status = db.Column(db.String(20), nullable=False, default="pending")
    source = db.Column(db.String(20), nullable=False, default="operator")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    employments = db.relationship("Employment", back_populates="company")
    contacts = db.relationship("CompanyContact", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company {self.business_name}>"


class ParticipantProfile(db.Model):
    __tablename__ = "participant_profiles"

    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    birth_place = db.Column(db.String(160), nullable=False, default="")
    birth_date = db.Column(db.Date, nullable=True)
    tax_code = db.Column(db.String(32), nullable=False, default="")
    certificate_title = db.Column(db.String(40), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    user = db.relationship("User", back_populates="participant_profile")
    employments = db.relationship(
        "Employment", back_populates="participant", cascade="all, delete-orphan"
    )

    @property
    def current_employment(self):
        return next((item for item in self.employments if item.is_current), None)


class Employment(db.Model):
    __tablename__ = "employments"
    __table_args__ = (
        db.UniqueConstraint(
            "participant_user_id", "company_id", "started_on", name="uq_employment_period"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    participant_user_id = db.Column(
        db.String(36),
        db.ForeignKey("participant_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = db.Column(
        db.String(36), db.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    started_on = db.Column(db.Date, nullable=False, default=date.today)
    ended_on = db.Column(db.Date, nullable=True)
    is_current = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    participant = db.relationship("ParticipantProfile", back_populates="employments")
    company = db.relationship("Company", back_populates="employments")


class CompanyContact(db.Model):
    __tablename__ = "company_contacts"
    __table_args__ = (
        db.UniqueConstraint("company_id", "user_id", name="uq_company_contact_user"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    company_id = db.Column(
        db.String(36), db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    company = db.relationship("Company", back_populates="contacts")
    user = db.relationship("User")


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    title = db.Column(db.String(240), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    code = db.Column(db.String(16), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    creator_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    referent_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    delivery_mode = db.Column(db.String(20), nullable=False, default="online")
    meeting_url = db.Column(db.String(500), nullable=False, default="")
    timezone_name = db.Column(db.String(64), nullable=False, default="Europe/Rome")
    certificate_validity_months = db.Column(db.Integer, nullable=True)
    certificate_template_id = db.Column(
        db.String(36), db.ForeignKey("certificate_templates.id", ondelete="SET NULL"), nullable=True
    )
    signature_asset_id = db.Column(
        db.String(36), db.ForeignKey("signature_assets.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    creator = db.relationship("User", foreign_keys=[creator_user_id])
    referent = db.relationship("User", foreign_keys=[referent_user_id])
    sessions = db.relationship(
        "CourseSession",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseSession.sequence",
    )
    documents = db.relationship(
        "CourseDocument", back_populates="course", cascade="all, delete-orphan"
    )
    admission_requests = db.relationship(
        "AdmissionRequest", back_populates="course", cascade="all, delete-orphan"
    )
    enrollments = db.relationship(
        "Enrollment", back_populates="course", cascade="all, delete-orphan"
    )
    questionnaires = db.relationship(
        "Questionnaire",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Questionnaire.sort_order",
    )
    certificate_template = db.relationship("CertificateTemplate", foreign_keys=[certificate_template_id])
    signature_asset = db.relationship("SignatureAsset", foreign_keys=[signature_asset_id])
    certificates = db.relationship("Certificate", back_populates="course")

    @property
    def first_session(self):
        return self.sessions[0] if self.sessions else None

    def __repr__(self) -> str:
        return f"<Course {self.code} {self.title}>"


class CourseSession(db.Model):
    __tablename__ = "course_sessions"
    __table_args__ = (
        db.UniqueConstraint("course_id", "sequence", name="uq_course_session_sequence"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = db.Column(db.String(160), nullable=False, default="Seduta unica")
    sequence = db.Column(db.Integer, nullable=False, default=1)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=False)

    course = db.relationship("Course", back_populates="sessions")


class StoredFile(db.Model):
    __tablename__ = "stored_files"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    storage_key = db.Column(db.String(500), unique=True, nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(160), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    uploaded_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    uploaded_by = db.relationship("User")


class CertificateTemplate(db.Model):
    __tablename__ = "certificate_templates"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(160), nullable=False, index=True)
    stored_file_id = db.Column(
        db.String(36), db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    placeholders = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    uploaded_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    stored_file = db.relationship("StoredFile")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])


class SignatureAsset(db.Model):
    __tablename__ = "signature_assets"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(160), nullable=False)
    signer_name = db.Column(db.String(160), nullable=False)
    signer_title = db.Column(db.String(160), nullable=False, default="")
    stored_file_id = db.Column(
        db.String(36), db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    uploaded_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    stored_file = db.relationship("StoredFile")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])


class CourseDocument(db.Model):
    __tablename__ = "course_documents"
    __table_args__ = (
        db.UniqueConstraint("course_id", "stored_file_id", name="uq_course_document_file"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stored_file_id = db.Column(
        db.String(36), db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    label = db.Column(db.String(160), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    course = db.relationship("Course", back_populates="documents")
    stored_file = db.relationship("StoredFile")


class AdmissionRequest(db.Model):
    __tablename__ = "admission_requests"
    __table_args__ = (
        db.UniqueConstraint("course_id", "participant_user_id", name="uq_course_admission_participant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    participant_message = db.Column(db.Text, nullable=False, default="")
    internal_note = db.Column(db.Text, nullable=False, default="")
    decision_message = db.Column(db.Text, nullable=False, default="")
    decided_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    course = db.relationship("Course", back_populates="admission_requests")
    participant = db.relationship("User", foreign_keys=[participant_user_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_user_id])
    enrollment = db.relationship("Enrollment", back_populates="admission_request", uselist=False)


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    __table_args__ = (
        db.UniqueConstraint("course_id", "participant_user_id", name="uq_course_enrollment_participant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    admission_request_id = db.Column(
        db.String(36), db.ForeignKey("admission_requests.id", ondelete="SET NULL"), unique=True
    )
    attendance_status = db.Column(db.String(20), nullable=False, default="pending")
    enrolled_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    course = db.relationship("Course", back_populates="enrollments")
    participant = db.relationship("User")
    admission_request = db.relationship("AdmissionRequest", back_populates="enrollment")
    certificate = db.relationship("Certificate", back_populates="enrollment", uselist=False)


class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    participant_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    company_id = db.Column(
        db.String(36), db.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enrollment_id = db.Column(
        db.String(36), db.ForeignKey("enrollments.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    pdf_file_id = db.Column(
        db.String(36), db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    template_id = db.Column(
        db.String(36), db.ForeignKey("certificate_templates.id", ondelete="SET NULL"), nullable=True
    )
    certificate_number = db.Column(db.String(80), unique=True, nullable=True, index=True)
    title_snapshot = db.Column(db.String(240), nullable=False)
    course_date = db.Column(db.Date, nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = db.Column(db.Date, nullable=True, index=True)
    source = db.Column(db.String(30), nullable=False, default="generated", index=True)
    verification_status = db.Column(db.String(20), nullable=False, default="verified", index=True)
    status = db.Column(db.String(20), nullable=False, default="valid", index=True)
    data_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    generated_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    course = db.relationship("Course", back_populates="certificates")
    participant = db.relationship("User", foreign_keys=[participant_user_id])
    company = db.relationship("Company", foreign_keys=[company_id])
    enrollment = db.relationship("Enrollment", back_populates="certificate")
    pdf_file = db.relationship("StoredFile", foreign_keys=[pdf_file_id])
    template = db.relationship("CertificateTemplate", foreign_keys=[template_id])
    generated_by = db.relationship("User", foreign_keys=[generated_by_user_id])


class ImportBatch(db.Model):
    __tablename__ = "import_batches"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    stored_file_id = db.Column(
        db.String(36), db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    course_title = db.Column(db.String(240), nullable=False)
    course_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="preview", index=True)
    detected_mapping = db.Column(db.JSON, nullable=False, default=dict)
    summary = db.Column(db.JSON, nullable=False, default=dict)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    created_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    stored_file = db.relationship("StoredFile")
    course = db.relationship("Course")
    created_by = db.relationship("User")
    rows = db.relationship(
        "ImportRow", back_populates="batch", cascade="all, delete-orphan", order_by="ImportRow.row_number"
    )


class ImportRow(db.Model):
    __tablename__ = "import_rows"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    batch_id = db.Column(
        db.String(36), db.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number = db.Column(db.Integer, nullable=False)
    source_rows = db.Column(db.JSON, nullable=False, default=list)
    email = db.Column(db.String(320), nullable=False, default="")
    first_name = db.Column(db.String(120), nullable=False, default="")
    last_name = db.Column(db.String(120), nullable=False, default="")
    birth_place = db.Column(db.String(160), nullable=False, default="")
    birth_date = db.Column(db.Date, nullable=True)
    certificate_title = db.Column(db.String(80), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="ready", index=True)
    warning = db.Column(db.Text, nullable=False, default="")
    participant_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    enrollment_id = db.Column(
        db.String(36), db.ForeignKey("enrollments.id", ondelete="SET NULL"), nullable=True
    )

    batch = db.relationship("ImportBatch", back_populates="rows")
    participant = db.relationship("User", foreign_keys=[participant_user_id])
    enrollment = db.relationship("Enrollment", foreign_keys=[enrollment_id])


class Questionnaire(db.Model):
    __tablename__ = "questionnaires"
    __table_args__ = (
        db.UniqueConstraint("course_id", "sort_order", name="uq_questionnaire_course_order"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    course_id = db.Column(
        db.String(36), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = db.Column(db.String(240), nullable=False)
    instructions = db.Column(db.Text, nullable=False, default="")
    passing_percentage = db.Column(db.Integer, nullable=False, default=70)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    sort_order = db.Column(db.Integer, nullable=False, default=1)
    version = db.Column(db.Integer, nullable=False, default=1)
    is_published = db.Column(db.Boolean, nullable=False, default=False, index=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    course = db.relationship("Course", back_populates="questionnaires")
    published_by = db.relationship("User")
    questions = db.relationship(
        "Question",
        back_populates="questionnaire",
        cascade="all, delete-orphan",
        order_by="Question.sort_order",
    )
    attempts = db.relationship("QuestionnaireAttempt", back_populates="questionnaire")

    @property
    def maximum_score(self) -> Decimal:
        return sum(
            (option.score_value for question in self.questions for option in question.options if option.is_correct),
            Decimal("0"),
        )

    @property
    def has_attempts(self) -> bool:
        return bool(self.attempts)


class Question(db.Model):
    __tablename__ = "questions"
    __table_args__ = (
        db.UniqueConstraint("questionnaire_id", "sort_order", name="uq_questionnaire_question_order"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    questionnaire_id = db.Column(
        db.String(36),
        db.ForeignKey("questionnaires.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt = db.Column(db.Text, nullable=False)
    response_type = db.Column(db.String(20), nullable=False, default="single")
    sort_order = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    questionnaire = db.relationship("Questionnaire", back_populates="questions")
    options = db.relationship(
        "QuestionOption",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionOption.sort_order",
    )


class QuestionOption(db.Model):
    __tablename__ = "question_options"
    __table_args__ = (
        db.UniqueConstraint("question_id", "sort_order", name="uq_question_option_order"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    question_id = db.Column(
        db.String(36), db.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    score_value = db.Column(db.Numeric(8, 2), nullable=False, default=Decimal("0"))
    sort_order = db.Column(db.Integer, nullable=False, default=1)

    question = db.relationship("Question", back_populates="options")


class QuestionnaireAttempt(db.Model):
    __tablename__ = "questionnaire_attempts"
    __table_args__ = (
        db.UniqueConstraint(
            "questionnaire_id", "participant_user_id", "attempt_number", name="uq_questionnaire_attempt_number"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    questionnaire_id = db.Column(
        db.String(36), db.ForeignKey("questionnaires.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    participant_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempt_number = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    score = db.Column(db.Numeric(8, 2), nullable=True)
    maximum_score = db.Column(db.Numeric(8, 2), nullable=True)
    passing_percentage_snapshot = db.Column(db.Integer, nullable=False)
    passed = db.Column(db.Boolean, nullable=True, index=True)
    answers_snapshot = db.Column(db.JSON, nullable=False, default=list)

    questionnaire = db.relationship("Questionnaire", back_populates="attempts")
    participant = db.relationship("User")
    answers = db.relationship(
        "AttemptAnswer", back_populates="attempt", cascade="all, delete-orphan"
    )


class AttemptAnswer(db.Model):
    __tablename__ = "attempt_answers"
    __table_args__ = (
        db.UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question_answer"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    attempt_id = db.Column(
        db.String(36),
        db.ForeignKey("questionnaire_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = db.Column(
        db.String(36), db.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    selected_option_ids = db.Column(db.JSON, nullable=False, default=list)
    awarded_score = db.Column(db.Numeric(8, 2), nullable=False, default=Decimal("0"))
    fully_correct = db.Column(db.Boolean, nullable=False, default=False)

    attempt = db.relationship("QuestionnaireAttempt", back_populates="answers")
    question = db.relationship("Question")
