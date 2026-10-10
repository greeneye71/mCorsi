#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_executable="$project_root/.venv/bin/python"
if [ ! -x "$python_executable" ]; then python_executable=python3; fi
export MCORSI_ENV=production
web_host=${MCORSI_WEB_HOST:-0.0.0.0}
web_port=${1:-${MCORSI_WEB_PORT:-5100}}
cd "$project_root"
instance_path=${MCORSI_INSTANCE_PATH:-$project_root/instance}
case "$instance_path" in
    /*) ;;
    *) printf 'ERRORE: MCORSI_INSTANCE_PATH deve essere un percorso assoluto.
' >&2; exit 2 ;;
esac
if ! mkdir -p "$instance_path" 2>/dev/null || [ ! -w "$instance_path" ]; then
    printf 'ERRORE: directory instance non scrivibile: %s
' "$instance_path" >&2
    printf 'Impostare MCORSI_INSTANCE_PATH su una directory scrivibile, per esempio /var/lib/mcorsi/instance.
' >&2
    exit 2
fi
printf 'Controllo della configurazione di cifratura...\n'
"$python_executable" -m mcorsi.startup_secrets prepare
secret_migration=0
if "$python_executable" -m mcorsi.startup_secrets pending; then
    secret_migration=1
    if "$python_executable" -m mcorsi.startup_secrets needs-backup; then
        printf 'Backup di sicurezza prima della migrazione dei segreti...\n'
        "$python_executable" -m flask --app wsgi backup create
    fi
fi
printf 'Controllo e applicazione delle migrazioni del database...\n'
"$python_executable" -m flask --app wsgi init-db
if [ "$secret_migration" -eq 1 ]; then
    if "$python_executable" -m mcorsi.startup_secrets needs-rotation; then
        printf 'Ricifratura dei segreti persistiti...\n'
        "$python_executable" -m flask --app wsgi admin rotate-encryption-key
    fi
    "$python_executable" -m mcorsi.startup_secrets complete
fi
exec "$python_executable" -m waitress --listen="$web_host:$web_port" --threads=4 wsgi:app
