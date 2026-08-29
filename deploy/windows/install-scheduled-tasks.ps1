param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$WebHost = "0.0.0.0",
    [int]$WebPort = 5100,
    [int]$McpPort = 8001
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Ambiente virtuale non trovato: $Python" }
$User = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$WebAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\run-production.ps1`" -PythonExecutable `"$Python`" -ListenAddress `"${WebHost}:$WebPort`""
$AtStartup = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "mCorsi Web" -Action $WebAction -Trigger $AtStartup -User $User -RunLevel Limited -Force

$McpAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\run-mcp.ps1`" -PythonExecutable `"$Python`" -Port $McpPort"
Register-ScheduledTask -TaskName "mCorsi MCP" -Action $McpAction -Trigger $AtStartup -User $User -RunLevel Limited -Force

$ReminderAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\notifications.ps1`" -PythonExecutable `"$Python`""
$EveryMorning = New-ScheduledTaskTrigger -Daily -At "08:00"
Register-ScheduledTask -TaskName "mCorsi Promemoria" -Action $ReminderAction -Trigger $EveryMorning -User $User -RunLevel Limited -Force

$BackupAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\backup.ps1`" -PythonExecutable `"$Python`""
$EveryNight = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "mCorsi Backup" -Action $BackupAction -Trigger $EveryNight -User $User -RunLevel Limited -Force

Write-Host "Attività pianificate mCorsi installate per $User (web ${WebHost}:$WebPort, MCP $McpPort)."
