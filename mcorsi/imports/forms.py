from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class HistoricalImportForm(FlaskForm):
    course_title = StringField("Titolo del corso", validators=[DataRequired(), Length(max=240)])
    course_date = DateField("Data del corso", validators=[DataRequired()])
    file = FileField("Esportazione Excel di Microsoft Forms", validators=[FileRequired(), FileAllowed(["xlsx"])])
    submit = SubmitField("Analizza file")


class ConfirmImportForm(FlaskForm):
    submit = SubmitField("Conferma e crea lo storico")
