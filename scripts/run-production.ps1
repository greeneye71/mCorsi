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
    & $PythonExecutable -m mcorsi.startup_secrets prepare
    if ($LASTEXITCODE -ne 0) { throw "Preparazione dei segreti terminata con codice $LASTEXITCODE." }
    & $PythonExecutable -m mcorsi.startup_secrets pending
    $SecretMigrationPending = $LASTEXITCODE -eq 0
    if ($LASTEXITCODE -gt 1) { throw "Controllo dei segreti terminato con codice $LASTEXITCODE." }
    if ($SecretMigrationPending) {
        & $PythonExecutable -m mcorsi.startup_secrets needs-backup
        $BackupRequired = $LASTEXITCODE -eq 0
        if ($LASTEXITCODE -gt 1) { throw "Controllo del backup terminato con codice $LASTEXITCODE." }
        if ($BackupRequired) {
            & $PythonExecutable -m flask --app wsgi backup create
            if ($LASTEXITCODE -ne 0) { throw "Backup di sicurezza terminato con codice $LASTEXITCODE." }
        }
    }
    & $PythonExecutable -m flask --app wsgi init-db
    if ($LASTEXITCODE -ne 0) { throw "Migrazione del database terminata con codice $LASTEXITCODE." }
    if ($SecretMigrationPending) {
        & $PythonExecutable -m mcorsi.startup_secrets needs-rotation
        $RotationRequired = $LASTEXITCODE -eq 0
        if ($LASTEXITCODE -gt 1) { throw "Controllo della rotazione terminato con codice $LASTEXITCODE." }
        if ($RotationRequired) {
            & $PythonExecutable -m flask --app wsgi admin rotate-encryption-key
            if ($LASTEXITCODE -ne 0) { throw "Rotazione dei segreti terminata con codice $LASTEXITCODE." }
        }
        & $PythonExecutable -m mcorsi.startup_secrets complete
        if ($LASTEXITCODE -ne 0) { throw "Chiusura della migrazione terminata con codice $LASTEXITCODE." }
    }
    & $PythonExecutable -m waitress --listen=$ListenAddress --threads=4 wsgi:app
    if ($LASTEXITCODE -ne 0) { throw "Waitress è terminato con codice $LASTEXITCODE." }
} finally {
    Pop-Location
}
