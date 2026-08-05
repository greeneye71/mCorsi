from __future__ import annotations

from datetime import date, time

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    EmailField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, URL, ValidationError


COURSE_STATUS_CHOICES = [
    ("draft", "Bozza"),
    ("open", "Aperto alle richieste"),
    ("in_progress", "In corso"),
    ("completed", "Concluso"),
    ("canceled", "Annullato"),
    ("archived", "Archiviato"),
]
DELIVERY_MODE_CHOICES = [
    ("online", "Online"),
    ("in_person", "In presenza"),
    ("hybrid", "Ibrido"),
]


class CourseForm(FlaskForm):
    title = StringField("Titolo", validators=[DataRequired(), Length(max=240)])
    description = TextAreaField("Descrizione", validators=[Optional(), Length(max=10000)])
    status = SelectField("Stato", choices=COURSE_STATUS_CHOICES, validators=[DataRequired()])
    referent_user_id = SelectField("Referente", validators=[DataRequired()])
    session_date = DateField("Data", validators=[DataRequired()], default=date.today)
    start_time = TimeField("Ora iniziale", validators=[DataRequired()], default=time(9, 0))
    end_time = TimeField("Ora finale", validators=[DataRequired()], default=time(13, 0))
    delivery_mode = SelectField("Modalità", choices=DELIVERY_MODE_CHOICES, validators=[DataRequired()])
    meeting_url = StringField(
        "Collegamento videoconferenza",
        validators=[Optional(), URL(require_tld=False), Length(max=500)],
    )
    certificate_validity_months = IntegerField(
        "Validità attestato in mesi",
        validators=[Optional(), NumberRange(min=1, max=600)],
    )
    submit = SubmitField("Salva corso")

    def validate_end_time(self, field):
        if self.start_time.data and field.data and field.data <= self.start_time.data:
            raise ValidationError("Deve essere successiva all'ora iniziale.")


class DuplicateCourseForm(FlaskForm):
    referent_user_id = SelectField("Referente", validators=[DataRequired()])
    session_date = DateField("Nuova data", validators=[DataRequired()])
    start_time = TimeField("Ora iniziale", validators=[DataRequired()])
    end_time = TimeField("Ora finale", validators=[DataRequired()])
    submit = SubmitField("Crea nuova edizione")

    def validate_end_time(self, field):
        if self.start_time.data and field.data and field.data <= self.start_time.data:
            raise ValidationError("Deve essere successiva all'ora iniziale.")


class AdmissionAddForm(FlaskForm):
    email = EmailField(
        "Email del partecipante", validators=[DataRequired(), Email(), Length(max=320)]
    )
    submit = SubmitField("Registra richiesta")


class AdmissionDecisionForm(FlaskForm):
    decision_message = StringField(
        "Messaggio per il partecipante", validators=[Optional(), Length(max=500)]
    )
    internal_note = StringField("Nota interna", validators=[Optional(), Length(max=500)])
