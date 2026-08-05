#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_executable="$project_root/.venv/bin/python"
if [ ! -x "$python_executable" ]; then python_executable=python3; fi
export MCORSI_ENV=production
web_host=${MCORSI_WEB_HOST:-0.0.0.0}
web_port=${1:-${MCORSI_WEB_PORT:-5100}}
cd "$project_root"
printf 'Controllo e applicazione delle migrazioni del database...\n'
"$python_executable" -m flask --app wsgi init-db
exec "$python_executable" -m waitress --listen="$web_host:$web_port" --threads=4 wsgi:app
