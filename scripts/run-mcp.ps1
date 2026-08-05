param(
    [string]$PythonExecutable = "",
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $VirtualEnvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualEnvPython) { $VirtualEnvPython } else { "python" }
}
if ($Port -gt 0) { $env:MCORSI_MCP_PORT = $Port.ToString() }
if (-not $env:MCORSI_MCP_PORT) { $env:MCORSI_MCP_PORT = "8001" }
$env:MCORSI_ENV = "production"
Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExecutable mcp_server.py
    if ($LASTEXITCODE -ne 0) { throw "Il server MCP è terminato con codice $LASTEXITCODE." }
} finally {
    Pop-Location
}
