#!/usr/bin/env sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_executable="$project_root/.venv/bin/python"
if [ ! -x "$python_executable" ]; then python_executable=python3; fi
cd "$project_root"
exec "$python_executable" -m flask --app wsgi notifications run
