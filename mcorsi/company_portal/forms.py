from flask_wtf import FlaskForm
from wtforms import EmailField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Regexp


class CompanyAccessForm(FlaskForm):
    email = EmailField("Email aziendale", validators=[DataRequired(), Email(), Length(max=320)])
    vat_number = StringField("Partita IVA", validators=[DataRequired(), Length(max=32)])
    submit = SubmitField("Invia codice")


class CompanyVerifyForm(FlaskForm):
    code = StringField(
        "Codice temporaneo",
        validators=[DataRequired(), Regexp(r"^\d{6}$", message="Inserisci le 6 cifre del codice.")],
    )
    submit = SubmitField("Accedi")
