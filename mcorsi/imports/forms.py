from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class HistoricalImportForm(FlaskForm):
    course_title = StringField("Titolo del corso", validators=[DataRequired(), Length(max=240)])
    course_date = DateField("Data del corso", validators=[DataRequired()])
    file = FileField("Esportazione Excel di Microsoft Forms", validators=[FileRequired(), FileAllowed(["xlsx"])])
    submit = SubmitField("Analizza file")


class ConfirmImportForm(FlaskForm):
    attendance_status = SelectField(
        "Stato delle presenze importate",
        choices=[
            ("pending", "Da confermare"),
            ("attended", "Presenti"),
            ("absent", "Assenti"),
        ],
        default="pending",
        validators=[DataRequired()],
    )
    submit = SubmitField("Conferma e crea lo storico")
