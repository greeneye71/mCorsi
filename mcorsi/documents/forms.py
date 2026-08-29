from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class CourseDocumentForm(FlaskForm):
    label = StringField("Descrizione", validators=[Optional(), Length(max=160)])
    file = FileField(
        "File",
        validators=[
            FileRequired(),
            FileAllowed(
                [
                    "csv",
                    "docx",
                    "jpeg",
                    "jpg",
                    "ods",
                    "odt",
                    "pdf",
                    "png",
                    "pptx",
                    "txt",
                    "xlsx",
                ],
                "Formato del documento non consentito.",
            ),
        ],
    )
    submit = SubmitField("Carica documento")


class TemplateUploadForm(FlaskForm):
    name = StringField("Nome modello", validators=[DataRequired(), Length(max=160)])
    file = FileField(
        "Modello DOCX",
        validators=[FileRequired(), FileAllowed(["docx"], "Seleziona un file DOCX.")],
    )
    submit = SubmitField("Carica modello")


class SignatureUploadForm(FlaskForm):
    name = StringField("Nome interno", validators=[DataRequired(), Length(max=160)])
    signer_name = StringField("Nome del firmatario", validators=[DataRequired(), Length(max=160)])
    signer_title = StringField("Qualifica", validators=[Optional(), Length(max=160)])
    file = FileField(
        "Firma PNG o JPEG",
        validators=[
            FileRequired(),
            FileAllowed(["png", "jpg", "jpeg"], "Seleziona un'immagine PNG o JPEG."),
        ],
    )
    submit = SubmitField("Carica firma")


class CourseCertificateSettingsForm(FlaskForm):
    certificate_template_id = SelectField("Modello attestato", validators=[DataRequired()])
    signature_asset_id = SelectField("Firma", validators=[Optional()])
    submit = SubmitField("Salva configurazione")


class AttendanceForm(FlaskForm):
    attendance_status = SelectField(
        "Presenza",
        choices=[("pending", "Da confermare"), ("attended", "Presente"), ("absent", "Assente")],
        validators=[DataRequired()],
    )


class ParticipantCertificateUploadForm(FlaskForm):
    title = StringField("Corso o attestato", validators=[DataRequired(), Length(max=240)])
    course_date = DateField("Data del corso", validators=[DataRequired()])
    expires_at = DateField("Scadenza", validators=[Optional()])
    file = FileField(
        "Attestato PDF",
        validators=[FileRequired(), FileAllowed(["pdf"], "Seleziona un file PDF.")],
    )
    submit = SubmitField("Carica attestato")
