param(
    [string]$ListenAddress = "127.0.0.1:8000",
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $VirtualEnvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualEnvPython) { $VirtualEnvPython } else { "python" }
}
$env:MCORSI_ENV = "production"
Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExecutable -m waitress --listen=$ListenAddress --threads=4 wsgi:app
    if ($LASTEXITCODE -ne 0) { throw "Waitress è terminato con codice $LASTEXITCODE." }
} finally {
    Pop-Location
}
