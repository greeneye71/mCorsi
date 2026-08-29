from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, IntegerField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError

from ..services.passwords import PASSWORD_POLICY_MESSAGE, password_is_valid


def validate_staff_password(_form, field):
    if not password_is_valid(field.data or ""):
        raise ValidationError(PASSWORD_POLICY_MESSAGE)


class StaffCreateForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=160)])
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=320)])
    role = SelectField(
        "Ruolo", choices=[("operator", "Operatore"), ("admin", "Amministratore")]
    )
    password = PasswordField(
        "Password iniziale",
        validators=[DataRequired(), Length(max=128), validate_staff_password],
    )
    password_confirm = PasswordField(
        "Conferma password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Crea account")


class StaffPasswordForm(FlaskForm):
    password = PasswordField(
        "Nuova password",
        validators=[DataRequired(), Length(max=128), validate_staff_password],
    )
    password_confirm = PasswordField(
        "Conferma password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Reimposta password")


class StaffNameForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=160)])
    submit = SubmitField("Salva nome")


class StaffStateForm(FlaskForm):
    submit = SubmitField("Cambia stato")


class SmtpSettingsForm(FlaskForm):
    host = StringField("Server SMTP", validators=[DataRequired(), Length(max=255)])
    port = IntegerField("Porta", validators=[DataRequired(), NumberRange(min=1, max=65535)], default=587)
    username = StringField("Username", validators=[Optional(), Length(max=320)])
    password = PasswordField("Password", validators=[Optional(), Length(max=500)])
    from_email = EmailField("Email mittente", validators=[DataRequired(), Email(), Length(max=320)])
    from_name = StringField("Nome mittente", validators=[DataRequired(), Length(max=160)], default="mCorsi")
    use_starttls = BooleanField("STARTTLS", default=True)
    use_ssl = BooleanField("SSL/TLS diretto")
    timeout_seconds = IntegerField(
        "Timeout in secondi", validators=[DataRequired(), NumberRange(min=5, max=120)], default=20
    )
    test_recipient = EmailField(
        "Destinatario email di prova", validators=[Optional(), Email(), Length(max=320)]
    )
    save = SubmitField("Salva configurazione")
    save_and_test = SubmitField("Salva e invia prova")

    def validate_use_ssl(self, field):
        if field.data and self.use_starttls.data:
            raise ValidationError("SSL diretto e STARTTLS non possono essere attivi insieme.")
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if (
            not field.data
            and not self.use_starttls.data
            and (self.host.data or "").strip().casefold() not in local_hosts
        ):
            raise ValidationError("Attiva SSL/TLS o STARTTLS per i server SMTP remoti.")


class NotificationSettingsForm(FlaskForm):
    course_reminders_enabled = BooleanField("Invia promemoria prima dei corsi", default=True)
    course_reminder_days = IntegerField(
        "Giorni prima del corso", validators=[DataRequired(), NumberRange(min=1, max=30)], default=3
    )
    certificate_reminders_enabled = BooleanField("Avvisa per gli attestati in scadenza", default=True)
    certificate_expiry_days = IntegerField(
        "Anticipo scadenza in giorni", validators=[DataRequired(), NumberRange(min=7, max=730)], default=180
    )
    submit = SubmitField("Salva promemoria")


class RunNotificationsForm(FlaskForm):
    submit = SubmitField("Accoda e invia ora")
