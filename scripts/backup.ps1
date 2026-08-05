param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if (-not $PythonExecutable) {
    $VirtualEnvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualEnvPython) {
        $VirtualEnvPython
    } else {
        "python"
    }
}

Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExecutable -m flask --app wsgi backup create
    if ($LASTEXITCODE -ne 0) {
        throw "Il backup mCorsi è terminato con codice $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
