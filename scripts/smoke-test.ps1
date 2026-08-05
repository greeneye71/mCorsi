param([string]$PythonExecutable = "")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $VirtualEnvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualEnvPython) { $VirtualEnvPython } else { "python" }
}
$EnvironmentNames = @(
    "MCORSI_ENV",
    "MCORSI_SECRET_KEY",
    "MCORSI_ENCRYPTION_KEY",
    "MCORSI_OTP_PEPPER",
    "MCORSI_MCP_TOKEN_PEPPER",
    "MCORSI_WEB_HOST",
    "MCORSI_WEB_PORT",
    "MCORSI_MCP_PORT",
    "MCORSI_MCP_ALLOWED_HOSTS"
)
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}
$env:MCORSI_ENV = "production"
$env:MCORSI_SECRET_KEY = "smoke-test-secret-key-web"
$env:MCORSI_ENCRYPTION_KEY = "smoke-test-encryption-key"
$env:MCORSI_OTP_PEPPER = "smoke-test-otp-pepper"
$env:MCORSI_MCP_TOKEN_PEPPER = "smoke-test-mcp-token-pepper"
$env:MCORSI_WEB_HOST = "0.0.0.0"
$env:MCORSI_WEB_PORT = "18000"
$env:MCORSI_MCP_PORT = "18001"
$env:MCORSI_MCP_ALLOWED_HOSTS = "127.0.0.1:18001,localhost:18001"
$WebProcess = $null
$McpProcess = $null
Push-Location -LiteralPath $ProjectRoot
try {
    $WebProcess = Start-Process -FilePath $PythonExecutable -ArgumentList @("-m", "waitress", "--listen=0.0.0.0:18000", "--threads=2", "wsgi:app") -PassThru -WindowStyle Hidden
    $McpProcess = Start-Process -FilePath $PythonExecutable -ArgumentList @("mcp_server.py") -PassThru -WindowStyle Hidden

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:18000/health/ready" -TimeoutSec 2
            if ($Health.status -in @("ok", "degraded")) { $Ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $Ready) { throw "Il server web non ha superato il controllo di disponibilità." }

    $Unauthorized = $false
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:18001/mcp" -Method Post -ContentType "application/json" -Headers @{Accept="application/json, text/event-stream"} -Body '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' -TimeoutSec 5 | Out-Null
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 401) { $Unauthorized = $true }
    }
    if (-not $Unauthorized) { throw "Il server MCP non ha rifiutato la richiesta priva di token." }
    Write-Host "Smoke test superato: web disponibile e MCP protetto."
} finally {
    if ($McpProcess -and -not $McpProcess.HasExited) { Stop-Process -Id $McpProcess.Id -Force }
    if ($WebProcess -and -not $WebProcess.HasExited) { Stop-Process -Id $WebProcess.Id -Force }
    foreach ($Name in $EnvironmentNames) {
        $PreviousValue = $PreviousEnvironment[$Name]
        if ($null -eq $PreviousValue) {
            Remove-Item -Path "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$Name" -Value $PreviousValue
        }
    }
    Pop-Location
}
