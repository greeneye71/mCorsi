from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import DateField, EmailField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional


class ParticipantForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=320)])
    first_name = StringField("Nome", validators=[DataRequired(), Length(max=120)])
    last_name = StringField("Cognome", validators=[DataRequired(), Length(max=120)])
    birth_place = StringField("Luogo di nascita", validators=[Optional(), Length(max=160)])
    birth_date = DateField("Data di nascita", validators=[Optional()])
    tax_code = StringField("Codice fiscale", validators=[Optional(), Length(max=32)])
    mobile_phone = StringField("Telefono", validators=[Optional(), Length(max=32)])
    certificate_title = StringField(
        "Titolo da riportare sull'attestato", validators=[Optional(), Length(max=40)]
    )
    company_id = SelectField("Azienda attuale", validators=[Optional()])
    submit = SubmitField("Salva partecipante")


class CompanyForm(FlaskForm):
    business_name = StringField("Ragione sociale", validators=[DataRequired(), Length(max=240)])
    vat_number = StringField("Partita IVA", validators=[DataRequired(), Length(min=5, max=32)])
    tax_code = StringField("Codice fiscale", validators=[Optional(), Length(max=32)])
    address = StringField("Indirizzo", validators=[DataRequired(), Length(max=240)])
    postal_code = StringField("CAP", validators=[DataRequired(), Length(max=16)])
    city = StringField("Comune", validators=[DataRequired(), Length(max=120)])
    province = StringField("Provincia", validators=[Optional(), Length(max=8)])
    country = StringField("Nazione", validators=[DataRequired(), Length(min=2, max=2)], default="IT")
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=320)])
    pec = EmailField("PEC", validators=[Optional(), Email(), Length(max=320)])
    verification_status = SelectField(
        "Verifica",
        choices=[("pending", "Da verificare"), ("verified", "Verificata"), ("rejected", "Non valida")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Salva azienda")
