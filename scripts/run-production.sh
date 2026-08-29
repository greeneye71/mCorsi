#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_executable="$project_root/.venv/bin/python"
if [ ! -x "$python_executable" ]; then python_executable=python3; fi
export MCORSI_ENV=production
web_host=${MCORSI_WEB_HOST:-0.0.0.0}
web_port=${1:-${MCORSI_WEB_PORT:-5100}}
cd "$project_root"
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
