from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class QuestionnaireForm(FlaskForm):
    title = StringField("Titolo", validators=[DataRequired(), Length(max=240)])
    instructions = TextAreaField("Istruzioni", validators=[Optional(), Length(max=5000)])
    passing_percentage = IntegerField(
        "Soglia minima (%)", validators=[DataRequired(), NumberRange(min=1, max=100)], default=70
    )
    submit = SubmitField("Salva questionario")


class QuestionForm(FlaskForm):
    prompt = TextAreaField("Domanda", validators=[DataRequired(), Length(max=5000)])
    response_type = SelectField(
        "Tipo di risposta",
        choices=[("single", "Scelta singola"), ("multiple", "Scelta multipla")],
        validators=[DataRequired()],
    )
    option_1_text = StringField("Opzione 1", validators=[Optional(), Length(max=2000)])
    option_1_correct = BooleanField("Corretta")
    option_1_score = DecimalField("Punti", validators=[Optional(), NumberRange(min=0, max=10000)], default=Decimal("1"))
    option_2_text = StringField("Opzione 2", validators=[Optional(), Length(max=2000)])
    option_2_correct = BooleanField("Corretta")
    option_2_score = DecimalField("Punti", validators=[Optional(), NumberRange(min=0, max=10000)], default=Decimal("0"))
    option_3_text = StringField("Opzione 3", validators=[Optional(), Length(max=2000)])
    option_3_correct = BooleanField("Corretta")
    option_3_score = DecimalField("Punti", validators=[Optional(), NumberRange(min=0, max=10000)], default=Decimal("0"))
    option_4_text = StringField("Opzione 4", validators=[Optional(), Length(max=2000)])
    option_4_correct = BooleanField("Corretta")
    option_4_score = DecimalField("Punti", validators=[Optional(), NumberRange(min=0, max=10000)], default=Decimal("0"))
    option_5_text = StringField("Opzione 5", validators=[Optional(), Length(max=2000)])
    option_5_correct = BooleanField("Corretta")
    option_5_score = DecimalField("Punti", validators=[Optional(), NumberRange(min=0, max=10000)], default=Decimal("0"))
    option_6_text = StringField("Opzione 6", validators=[Optional(), Length(max=2000)])
    option_6_correct = BooleanField("Corretta")
    option_6_score = DecimalField("Punti", validators=[Optional(), NumberRange(min=0, max=10000)], default=Decimal("0"))
    submit = SubmitField("Salva domanda")


class EmptyForm(FlaskForm):
    submit = SubmitField("Conferma")


class AttemptSubmissionForm(FlaskForm):
    submit = SubmitField("Invia risposte")
