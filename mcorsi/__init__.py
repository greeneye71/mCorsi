from __future__ import annotations

from pathlib import Path
from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from .cli import register_commands
from .config import CONFIGS
from .extensions import csrf, db, login_manager, migrate
from .services.secrets import is_fernet_key
from .version import APP_VERSION, DATABASE_VERSION


def create_app(config_name: str = "production", test_config: dict | None = None) -> Flask:
    if config_name not in CONFIGS:
        raise RuntimeError(f"Configurazione applicativa sconosciuta: {config_name}")
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(CONFIGS[config_name])
    if test_config:
        app.config.update(test_config)

    if config_name == "production":
        insecure = []
        placeholder_secrets = {
            "development-only-change-me",
            "cambia-questo-valore",
            "usa-un-secondo-valore-lungo-e-casuale",
            "usa-un-terzo-valore-lungo-e-casuale",
            "usa-un-quarto-valore-lungo-e-casuale",
        }
        configured_secrets = {
            "MCORSI_SECRET_KEY": app.config["SECRET_KEY"],
            "MCORSI_ENCRYPTION_KEY": app.config["ENCRYPTION_KEY"],
            "MCORSI_OTP_PEPPER": app.config["OTP_PEPPER"],
            "MCORSI_MCP_TOKEN_PEPPER": app.config["MCP_TOKEN_PEPPER"],
        }
        insecure.extend(
            name
            for name, value in configured_secrets.items()
            if value in placeholder_secrets or len(value) < 32
        )
        if not is_fernet_key(app.config["ENCRYPTION_KEY"]):
            insecure.append("MCORSI_ENCRYPTION_KEY")
        previous_keys = app.config.get("ENCRYPTION_PREVIOUS_KEYS", "")
        if any(
            not is_fernet_key(value.strip())
            for value in previous_keys.split(",")
            if value.strip()
        ):
            insecure.append("MCORSI_ENCRYPTION_PREVIOUS_KEYS")
        if len(set(configured_secrets.values())) != len(configured_secrets):
            insecure.extend(configured_secrets)
        insecure = sorted(set(insecure))
        if insecure:
            raise RuntimeError(
                "Configurazione di produzione non sicura. Imposta valori distinti per: "
                + ", ".join(insecure)
            )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["PRIVATE_STORAGE_PATH"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["BACKUP_PATH"]).mkdir(parents=True, exist_ok=True)

    if app.config.get("TRUST_PROXY_HEADERS"):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
            x_port=1,
        )

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth.routes import auth_bp
    from .courses.routes import courses_bp
    from .company_portal.routes import company_portal_bp
    from .documents.routes import documents_bp
    from .imports.routes import imports_bp
    from .main.routes import main_bp
    from .participants.routes import companies_bp, participants_bp
    from .portal.routes import portal_bp
    from .questionnaires.routes import questionnaires_bp
    from .settings.routes import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(company_portal_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(companies_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(questionnaires_bp)
    app.register_blueprint(settings_bp)
    register_commands(app)

    @app.template_filter("local_datetime")
    def local_datetime_filter(value, fmt="%d/%m/%Y · %H:%M"):
        if value is None:
            return "—"
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(ZoneInfo("Europe/Rome")).strftime(fmt)

    @app.context_processor
    def shared_labels():
        return {
            "course_status_labels": {
                "draft": "Bozza",
                "open": "Aperto",
                "in_progress": "In corso",
                "completed": "Concluso",
                "canceled": "Annullato",
                "archived": "Archiviato",
            },
            "admission_status_labels": {
                "pending": "In attesa",
                "approved": "Ammesso",
                "rejected": "Rifiutato",
            },
            "company_status_labels": {
                "pending": "Da verificare",
                "verified": "Verificata",
                "rejected": "Non valida",
            },
            "attendance_status_labels": {
                "pending": "Da confermare",
                "attended": "Presente",
                "absent": "Assente",
            },
            "app_version": APP_VERSION,
            "required_database_version": DATABASE_VERSION,
        }

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error("Errore interno non gestito", exc_info=error)
        return render_template("errors/500.html"), 500

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    return app
