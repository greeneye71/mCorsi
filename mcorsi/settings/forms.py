from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, IntegerField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError


class StaffCreateForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=320)])
    role = SelectField(
        "Ruolo", choices=[("operator", "Operatore"), ("admin", "Amministratore")]
    )
    password = PasswordField("Password iniziale", validators=[DataRequired(), Length(min=12, max=256)])
    password_confirm = PasswordField(
        "Conferma password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Crea account")


class StaffPasswordForm(FlaskForm):
    password = PasswordField("Nuova password", validators=[DataRequired(), Length(min=12, max=256)])
    password_confirm = PasswordField(
        "Conferma password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Reimposta password")


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
