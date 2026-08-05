#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

mode=${1:-test}
case "$mode" in
    test|sviluppo) mode=test ;;
    produzione|production) mode=produzione ;;
    *)
        printf 'Uso: sh avvia.sh [test|produzione] [porta]\n' >&2
        exit 2
        ;;
esac

if [ "$mode" = "produzione" ]; then
    port=${2:-${MCORSI_WEB_PORT:-8000}}
    export MCORSI_ENV=production
else
    port=${2:-${MCORSI_TEST_PORT:-5100}}
    export MCORSI_ENV=development
fi
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
export MCORSI_WEB_PORT=$port

printf '\n========================================\n'
printf '         Avvio di mCorsi\n'
printf '========================================\n\n'
printf 'Modalità: %s - Porta: %s\n\n' "$mode" "$port"

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
"$python_executable" -m pip install --disable-pip-version-check -q -r requirements.txt

printf '[3/4] Aggiornamento del database...\n'
"$python_executable" -m flask --app wsgi init-db

printf '[4/4] Controllo dell’amministratore...\n'
"$python_executable" -m flask --app wsgi admin bootstrap

printf '\nmCorsi è disponibile all’indirizzo:\n\n'
printf '    http://127.0.0.1:%s\n\n' "$port"
printf 'Premi CTRL+C per arrestare il programma.\n'
printf '========================================\n\n'

if [ "$mode" = "produzione" ]; then
    exec "$python_executable" -m waitress --listen="127.0.0.1:$port" --threads=4 wsgi:app
fi
exec "$python_executable" wsgi.py
