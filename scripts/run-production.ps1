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
    $WebHost = if ($env:MCORSI_WEB_HOST) { $env:MCORSI_WEB_HOST } else { "127.0.0.1" }
    $WebPort = if ($env:MCORSI_WEB_PORT) { $env:MCORSI_WEB_PORT } else { "8000" }
    $ListenAddress = "${WebHost}:${WebPort}"
}
$env:MCORSI_ENV = "production"
Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExecutable -m waitress --listen=$ListenAddress --threads=4 wsgi:app
    if ($LASTEXITCODE -ne 0) { throw "Waitress è terminato con codice $LASTEXITCODE." }
} finally {
    Pop-Location
}
