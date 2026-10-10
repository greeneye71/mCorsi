import sqlite3

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate(compare_type=True)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Accedi per continuare."
login_manager.login_message_category = "info"
csrf = CSRFProtect()


@event.listens_for(Engine, "connect")
def configure_sqlite(dbapi_connection, _connection_record) -> None:
    """Abilita integrità referenziale e una concorrenza adatta al singolo host."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


@login_manager.user_loader
def load_user(user_id: str):
    """Carica l'utente solo se il token di sessione non è stato revocato."""
    import hmac

    from .models import User

    raw_id, separator, token = (user_id or "").partition(":")
    if not separator or not token:
        return None
    user = db.session.get(User, raw_id)
    if user is None or not user.is_active or not user.session_token:
        return None
    if not hmac.compare_digest(user.session_token, token):
        return None
    return user
