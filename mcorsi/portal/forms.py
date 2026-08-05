from flask_wtf import FlaskForm
from wtforms import DateField, EmailField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp


class OtpRequestForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=320)])
    submit = SubmitField("Invia codice")


class OtpVerifyForm(FlaskForm):
    code = StringField(
        "Codice temporaneo",
        validators=[DataRequired(), Regexp(r"^\d{6}$", message="Inserisci le 6 cifre del codice.")],
    )
    submit = SubmitField("Accedi")


class ParticipantProfileForm(FlaskForm):
    first_name = StringField("Nome", validators=[DataRequired(), Length(max=120)])
    last_name = StringField("Cognome", validators=[DataRequired(), Length(max=120)])
    birth_place = StringField("Luogo di nascita", validators=[DataRequired(), Length(max=160)])
    birth_date = DateField("Data di nascita", validators=[DataRequired()])
    tax_code = StringField("Codice fiscale", validators=[Optional(), Length(max=32)])
    mobile_phone = StringField("Telefono", validators=[Optional(), Length(max=32)])
    certificate_title = StringField("Titolo", validators=[Optional(), Length(max=40)])
    vat_number = StringField("Partita IVA dell'azienda", validators=[Optional(), Length(max=32)])
    company_business_name = StringField("Ragione sociale", validators=[Optional(), Length(max=240)])
    company_tax_code = StringField("Codice fiscale azienda", validators=[Optional(), Length(max=32)])
    company_address = StringField("Indirizzo", validators=[Optional(), Length(max=240)])
    company_postal_code = StringField("CAP", validators=[Optional(), Length(max=16)])
    company_city = StringField("Comune", validators=[Optional(), Length(max=120)])
    company_province = StringField("Provincia", validators=[Optional(), Length(max=8)])
    company_country = StringField("Nazione", validators=[Optional(), Length(min=2, max=2)], default="IT")
    company_email = EmailField("Email azienda", validators=[Optional(), Email(), Length(max=320)])
    company_pec = EmailField("PEC", validators=[Optional(), Email(), Length(max=320)])
    submit = SubmitField("Salva e continua")


class CourseCodeForm(FlaskForm):
    code = StringField(
        "Codice corso",
        validators=[DataRequired(), Regexp(r"^[A-Za-z0-9 -]{6,20}$", message="Controlla il codice inserito.")],
    )
    submit = SubmitField("Chiedi l'ammissione")
