param(
    [string]$ListenAddress = "",
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $VirtualEnvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualEnvPython) { $VirtualEnvPython } else { "python" }
}
if (-not $ListenAddress) {
    $WebHost = if ($env:MCORSI_WEB_HOST) { $env:MCORSI_WEB_HOST } else { "0.0.0.0" }
    $WebPort = if ($env:MCORSI_WEB_PORT) { $env:MCORSI_WEB_PORT } else { "5100" }
    $ListenAddress = "${WebHost}:${WebPort}"
}
$env:MCORSI_ENV = "production"
Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExecutable -m flask --app wsgi init-db
    if ($LASTEXITCODE -ne 0) { throw "Migrazione del database terminata con codice $LASTEXITCODE." }
    & $PythonExecutable -m waitress --listen=$ListenAddress --threads=4 wsgi:app
    if ($LASTEXITCODE -ne 0) { throw "Waitress è terminato con codice $LASTEXITCODE." }
} finally {
    Pop-Location
}
