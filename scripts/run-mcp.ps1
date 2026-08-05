param([string]$PythonExecutable = "")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $VirtualEnvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualEnvPython) { $VirtualEnvPython } else { "python" }
}
$env:MCORSI_ENV = "production"
Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExecutable mcp_server.py
    if ($LASTEXITCODE -ne 0) { throw "Il server MCP è terminato con codice $LASTEXITCODE." }
} finally {
    Pop-Location
}
