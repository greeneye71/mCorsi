#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

mode=${1:-produzione}
case "$mode" in
    test|sviluppo) mode=test ;;
    produzione|production) mode=produzione ;;
    *)
        printf 'Uso: sh avvia.sh [test|produzione] [porta] [indirizzo]\n' >&2
        exit 2
        ;;
esac

if [ "$mode" = "produzione" ]; then
    export MCORSI_ENV=production
else
    export MCORSI_ENV=development
fi
port=${2:-${MCORSI_WEB_PORT:-5100}}
if [ "$mode" = "test" ]; then default_host=127.0.0.1; else default_host=0.0.0.0; fi
host=${3:-${MCORSI_WEB_HOST:-$default_host}}
case "$port" in
    ''|*[!0-9]*)
        printf 'ERRORE: la porta deve essere un numero, per esempio 5100.\n' >&2
        exit 2
        ;;
esac
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    printf 'ERRORE: la porta deve essere compresa tra 1 e 65535.\n' >&2
    exit 2
fi
export MCORSI_PORT=$port
export MCORSI_HOST=$host
export MCORSI_WEB_HOST=$host
export MCORSI_WEB_PORT=$port

printf '\n========================================\n'
printf '         Avvio di mCorsi\n'
printf '========================================\n\n'
printf 'Modalità: %s - Ascolto: %s:%s\n\n' "$mode" "$host" "$port"

if [ ! -x ".venv/bin/python" ]; then
    printf '[1/4] Creazione dell’ambiente Python...\n'
    if ! command -v python3 >/dev/null 2>&1; then
        printf '\nERRORE: Python 3 non è installato o non è disponibile nel PATH.\n' >&2
        exit 1
    fi
    if ! python3 -m venv .venv; then
        printf '\nERRORE: impossibile creare l’ambiente virtuale.\n' >&2
        printf 'Su Debian/Ubuntu può essere necessario: sudo apt install python3-venv\n' >&2
        exit 1
    fi
else
    printf '[1/4] Ambiente Python già presente.\n'
fi

python_executable="$project_root/.venv/bin/python"

printf '[2/4] Controllo delle dipendenze...\n'
"$python_executable" -m pip install --disable-pip-version-check -q --require-hashes -r requirements.lock

secret_migration=0
if [ "$mode" = "produzione" ]; then
    printf 'Controllo della configurazione di cifratura...\n'
    "$python_executable" -m mcorsi.startup_secrets prepare
    if "$python_executable" -m mcorsi.startup_secrets pending; then
        secret_migration=1
        if "$python_executable" -m mcorsi.startup_secrets needs-backup; then
            printf 'Backup di sicurezza prima della migrazione dei segreti...\n'
            "$python_executable" -m flask --app wsgi backup create
        fi
    fi
fi

printf '[3/4] Aggiornamento del database...\n'
"$python_executable" -m flask --app wsgi init-db

if [ "$secret_migration" -eq 1 ]; then
    if "$python_executable" -m mcorsi.startup_secrets needs-rotation; then
        printf 'Ricifratura dei segreti persistiti...\n'
        "$python_executable" -m flask --app wsgi admin rotate-encryption-key
    fi
    "$python_executable" -m mcorsi.startup_secrets complete
fi

printf '[4/4] Controllo dell’amministratore...\n'
"$python_executable" -m flask --app wsgi admin bootstrap

printf '\nmCorsi è disponibile su questo computer:\n\n'
printf '    http://127.0.0.1:%s\n\n' "$port"
printf 'Dalla rete locale usa l’indirizzo IP di questo computer:\n\n'
printf '    http://IP-DEL-COMPUTER:%s\n\n' "$port"
printf 'Per trovare l’indirizzo puoi eseguire: hostname -I\n'
printf 'Se non risponde, autorizza la porta %s nel firewall.\n\n' "$port"
printf 'Premi CTRL+C per arrestare il programma.\n'
printf '========================================\n\n'

if [ "$mode" = "produzione" ]; then
    exec "$python_executable" -m waitress --listen="$host:$port" --threads=4 wsgi:app
fi
exec "$python_executable" wsgi.py
