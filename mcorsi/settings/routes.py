from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from ..extensions import db
from ..models import EmailOutbox, NotificationConfiguration, Role, SmtpConfiguration, User, normalize_email
from ..services.audit import record_event
from ..services.mail import MailConfigurationError, MailDeliveryError, send_email
from ..services.permissions import admin_required
from ..services.secrets import SecretDecryptionError, encrypt_secret
from ..services.notifications import deliver_pending, enqueue_reminders
from .forms import (
    NotificationSettingsForm,
    RunNotificationsForm,
    SmtpSettingsForm,
    StaffCreateForm,
    StaffNameForm,
    StaffPasswordForm,
    StaffStateForm,
)


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.get("/")
@admin_required
def index():
    smtp_configuration = db.session.get(SmtpConfiguration, 1)
    notification_configuration = db.session.get(NotificationConfiguration, 1)
    staff_count = User.query.filter(
        User.roles.any(Role.name.in_(["admin", "operator"]))
    ).count()
    return render_template(
        "settings/index.html",
        smtp_configured=bool(smtp_configuration and smtp_configuration.host),
        notifications_configured=notification_configuration is not None,
        staff_count=staff_count,
    )


@settings_bp.route("/staff", methods=["GET", "POST"])
@admin_required
def staff():
    form = StaffCreateForm()
    if form.validate_on_submit():
        email = normalize_email(form.email.data)
        if User.query.filter_by(email=email).first():
            form.email.errors.append("Esiste già un account con questa email.")
        else:
            user = User(
                email=email,
                first_name=form.name.data.strip(),
                profile_completed=True,
            )
            user.set_password(form.password.data)
            user.roles.append(Role.query.filter_by(name=form.role.data).one())
            if form.role.data == "admin":
                user.roles.append(Role.query.filter_by(name="operator").one())
            db.session.add(user)
            db.session.flush()
            record_event(
                "admin.user_created_web",
                actor=current_user,
                target_type="user",
                target_id=user.id,
                detail={"email": email, "name": user.first_name, "role": form.role.data},
            )
            db.session.commit()
            flash("Account creato.", "success")
            return redirect(url_for("settings.staff"))
    users = (
        User.query.filter(User.roles.any(Role.name.in_(["admin", "operator"])))
        .order_by(User.email)
        .all()
    )
    return render_template(
        "settings/staff.html",
        form=form,
        name_form=StaffNameForm(),
        password_form=StaffPasswordForm(),
        state_form=StaffStateForm(),
        users=users,
    )


@settings_bp.post("/staff/<user_id>/name")
@admin_required
def staff_name(user_id: str):
    user = db.get_or_404(User, user_id)
    if not user.has_role("admin", "operator"):
        return redirect(url_for("settings.staff"))
    form = StaffNameForm()
    if form.validate_on_submit():
        user.first_name = form.name.data.strip()
        user.last_name = ""
        record_event(
            "admin.user_name_changed_web",
            actor=current_user,
            target_type="user",
            target_id=user.id,
            detail={"name": user.first_name},
        )
        db.session.commit()
        flash(f"Nome aggiornato per {user.email}.", "success")
    else:
        flash("Inserisci un nome valido.", "error")
    return redirect(url_for("settings.staff"))


@settings_bp.post("/staff/<user_id>/password")
@admin_required
def staff_password(user_id: str):
    user = db.get_or_404(User, user_id)
    if not user.has_role("admin", "operator"):
        return redirect(url_for("settings.staff"))
    form = StaffPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        record_event(
            "admin.password_changed_web",
            actor=current_user,
            target_type="user",
            target_id=user.id,
        )
        db.session.commit()
        flash(f"Password aggiornata per {user.email}.", "success")
    else:
        flash(
            "La password non rispetta i requisiti oppure le conferme non coincidono.",
            "error",
        )
    return redirect(url_for("settings.staff"))


@settings_bp.post("/staff/<user_id>/state")
@admin_required
def staff_state(user_id: str):
    user = db.get_or_404(User, user_id)
    form = StaffStateForm()
    if not user.has_role("admin", "operator"):
        return redirect(url_for("settings.staff"))
    if not form.validate_on_submit():
        return redirect(url_for("settings.staff"))
    if user.id == current_user.id and user.is_active:
        flash("Non puoi disabilitare il tuo account mentre lo stai usando.", "error")
        return redirect(url_for("settings.staff"))
    user.is_active = not user.is_active
    record_event(
        "admin.user_enabled_web" if user.is_active else "admin.user_disabled_web",
        actor=current_user,
        target_type="user",
        target_id=user.id,
    )
    db.session.commit()
    flash("Stato account aggiornato.", "success")
    return redirect(url_for("settings.staff"))


@settings_bp.route("/smtp", methods=["GET", "POST"])
@admin_required
def smtp():
    configuration = db.session.get(SmtpConfiguration, 1)
    form = SmtpSettingsForm(obj=configuration)
    if form.validate_on_submit():
        if configuration is None:
            configuration = SmtpConfiguration(id=1, updated_by_user_id=current_user.id)
            db.session.add(configuration)
        configuration.host = form.host.data.strip()
        configuration.port = form.port.data
        configuration.username = (form.username.data or "").strip()
        if form.password.data:
            configuration.password_encrypted = encrypt_secret(form.password.data)
        configuration.from_email = form.from_email.data.strip().casefold()
        configuration.from_name = form.from_name.data.strip()
        configuration.use_starttls = form.use_starttls.data
        configuration.use_ssl = form.use_ssl.data
        configuration.timeout_seconds = form.timeout_seconds.data
        configuration.updated_by_user_id = current_user.id
        record_event(
            "settings.smtp_updated", actor=current_user, target_type="smtp_configuration", target_id="1"
        )
        db.session.commit()

        if form.save_and_test.data:
            if not form.test_recipient.data:
                form.test_recipient.errors.append("Indica il destinatario della prova.")
            else:
                try:
                    send_email(
                        recipient=form.test_recipient.data,
                        subject="Email di prova mCorsi",
                        text_body="La configurazione SMTP di mCorsi funziona correttamente.",
                    )
                    flash("Configurazione salvata ed email di prova inviata.", "success")
                    return redirect(url_for("settings.smtp"))
                except (MailConfigurationError, MailDeliveryError, SecretDecryptionError) as exc:
                    flash(str(exc), "error")
        else:
            flash("Configurazione SMTP salvata.", "success")
            return redirect(url_for("settings.smtp"))

    if not form.is_submitted() and configuration is None:
        form.port.data = 587
        form.from_name.data = "mCorsi"
        form.use_starttls.data = True
        form.timeout_seconds.data = 20
    return render_template(
        "settings/smtp.html",
        form=form,
        password_configured=bool(configuration and configuration.password_encrypted),
    )


@settings_bp.route("/notifications", methods=["GET", "POST"])
@admin_required
def notifications():
    configuration = db.session.get(NotificationConfiguration, 1)
    form = NotificationSettingsForm(obj=configuration)
    if form.validate_on_submit():
        if configuration is None:
            configuration = NotificationConfiguration(id=1, updated_by_user_id=current_user.id)
            db.session.add(configuration)
        configuration.course_reminders_enabled = form.course_reminders_enabled.data
        configuration.course_reminder_days = form.course_reminder_days.data
        configuration.certificate_reminders_enabled = form.certificate_reminders_enabled.data
        configuration.certificate_expiry_days = form.certificate_expiry_days.data
        configuration.updated_by_user_id = current_user.id
        record_event("settings.notifications_updated", actor=current_user, target_type="notification_configuration", target_id="1")
        db.session.commit()
        flash("Configurazione promemoria salvata.", "success")
        return redirect(url_for("settings.notifications"))
    if not form.is_submitted() and configuration is None:
        form.course_reminders_enabled.data = True
        form.course_reminder_days.data = 3
        form.certificate_reminders_enabled.data = True
        form.certificate_expiry_days.data = 180
    recent = EmailOutbox.query.order_by(EmailOutbox.created_at.desc()).limit(50).all()
    return render_template(
        "settings/notifications.html", form=form, run_form=RunNotificationsForm(), messages=recent
    )


@settings_bp.post("/notifications/run")
@admin_required
def run_notifications():
    form = RunNotificationsForm()
    if form.validate_on_submit():
        queued = enqueue_reminders()
        delivered = deliver_pending()
        flash(
            f"Operazione completata: {sum(queued.values())} accodate, {delivered['sent']} inviate, {delivered['deferred']} rinviate.",
            "success",
        )
    return redirect(url_for("settings.notifications"))
