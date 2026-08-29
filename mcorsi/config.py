from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _environment_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


class BaseConfig:
    SECRET_KEY = os.environ.get("MCORSI_SECRET_KEY", "development-only-change-me")
    ENCRYPTION_KEY = os.environ.get("MCORSI_ENCRYPTION_KEY", SECRET_KEY)
    ENCRYPTION_PREVIOUS_KEYS = os.environ.get("MCORSI_ENCRYPTION_PREVIOUS_KEYS", "")
    LEGACY_ENCRYPTION_KEY = os.environ.get("MCORSI_LEGACY_ENCRYPTION_KEY", "")
    OTP_PEPPER = os.environ.get("MCORSI_OTP_PEPPER", SECRET_KEY)
    MCP_TOKEN_PEPPER = os.environ.get("MCORSI_MCP_TOKEN_PEPPER", SECRET_KEY)
    MCP_PUBLIC_URL = os.environ.get("MCORSI_MCP_PUBLIC_URL", "http://127.0.0.1:8001/mcp")
    MCP_HOST = os.environ.get("MCORSI_MCP_HOST", "127.0.0.1")
    MCP_PORT = int(os.environ.get("MCORSI_MCP_PORT", "8001"))
    MCP_ALLOWED_HOSTS = os.environ.get(
        "MCORSI_MCP_ALLOWED_HOSTS", "127.0.0.1:8001,localhost:8001"
    )
    MCP_ALLOWED_ORIGINS = os.environ.get("MCORSI_MCP_ALLOWED_ORIGINS", "")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "MCORSI_DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'mcorsi-v2.sqlite3'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PRIVATE_STORAGE_PATH = os.environ.get(
        "MCORSI_STORAGE_PATH", str(INSTANCE_DIR / "storage")
    )
    BACKUP_PATH = os.environ.get(
        "MCORSI_BACKUP_PATH", str(INSTANCE_DIR / "backups")
    )
    BACKUP_ENCRYPTION_KEY = os.environ.get("MCORSI_BACKUP_ENCRYPTION_KEY", "")
    BACKUP_DECRYPTION_KEYS = os.environ.get("MCORSI_BACKUP_DECRYPTION_KEYS", "")
    BACKUP_RETENTION_COUNT = int(os.environ.get("MCORSI_BACKUP_RETENTION_COUNT", "30"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MCORSI_MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
    LIBREOFFICE_PATH = os.environ.get("MCORSI_LIBREOFFICE_PATH", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = 2 * 60 * 60
    TRUST_PROXY_HEADERS = _environment_flag("MCORSI_TRUST_PROXY_HEADERS")
    OTP_EXPIRY_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5
    OTP_RESEND_COOLDOWN_SECONDS = 60
    OTP_MAX_PER_HOUR = 5
    OTP_MAX_PER_IP_HOUR = 20
    OTP_MAX_GLOBAL_PER_HOUR = 200
    PASSWORD_MAX_FAILURES = 10
    PASSWORD_FAILURE_WINDOW_MINUTES = 15
    QUESTIONNAIRE_ATTEMPT_EXPIRY_MINUTES = int(
        os.environ.get("MCORSI_QUESTIONNAIRE_ATTEMPT_EXPIRY_MINUTES", "60")
    )
    MAIL_BACKEND = "smtp"


class DevelopmentConfig(BaseConfig):
    ENV = "development"
    DEBUG = True


class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


class TestingConfig(BaseConfig):
    TESTING = True
    WTF_CSRF_ENABLED = False
    MAIL_BACKEND = "memory"


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
