"""Caricamento del file .env per gli entrypoint, prima di importare mcorsi.

mcorsi.config legge os.environ all'importazione: questo modulo sta fuori dal
pacchetto apposta, così il .env (MCORSI_ENV_FILE oppure .env nella radice del
progetto) è già nell'ambiente quando mcorsi viene importato.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent


def resolve_env_path() -> Path:
    raw = os.environ.get("MCORSI_ENV_FILE", "").strip()
    if not raw:
        return PROJECT_ROOT / ".env"
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("MCORSI_ENV_FILE deve essere un percorso assoluto.")
    return path


def load_env_file() -> Path:
    path = resolve_env_path()
    load_dotenv(path)
    return path
