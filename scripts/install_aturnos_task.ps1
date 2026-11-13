$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$syncScript = Join-Path $projectRoot "scripts\sync_aturnos.py"

$taskName = "AMH - Consulta aTurnos DEV"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "No se encuentra Python: $pythonPath"
}

if (-not (Test-Path -LiteralPath $syncScript)) {
    throw "No se encuentra el script: $syncScript"
}

# Comprueba el entorno sin mostrar credenciales.
Push-Location $projectRoot

try {
    & $pythonPath -c @"
from sqlalchemy import text
from app.config import settings
from app.db import engine

with engine.connect() as connection:
    database = connection.scalar(text("SELECT current_database()"))

if database != "amh_dev":
    raise SystemExit("La tarea DEV requiere la base amh_dev")

if not (
    settings.amh_aturnos_token
    and settings.amh_aturnos_token.get_secret_value().strip()
):
    raise SystemExit("Falta configurar AMH_ATURNOS_TOKEN")

print("Base de datos: " + database)
print("Token configurado: si")
"@

    if ($LASTEXITCODE -ne 0) {
        throw "No se ha superado la comprobacion del entorno."
    }
}
finally {
    Pop-Location
}

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "-m scripts.sync_aturnos" `
    -WorkingDirectory $projectRoot

# La primera repeticion sera dentro de una hora.
$hourlyTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddHours(8) `
    -RepetitionInterval (New-TimeSpan -Hours 8)

$logonTrigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $currentUser

# No almacena la contrasena de Windows.
# Ejecuta mientras este usuario tenga una sesion iniciada.
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

$taskSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$task = New-ScheduledTask `
    -Action $action `
    -Trigger @($hourlyTrigger, $logonTrigger) `
    -Principal $principal `
    -Settings $taskSettings `
    -Description "Consulta aTurnos y registra la comparacion con AMH. No crea usuarios ni modifica accesos."

Register-ScheduledTask `
    -TaskName $taskName `
    -InputObject $task `
    -Force |
    Out-Null

Write-Host ""
Write-Host "Tarea registrada: $taskName" -ForegroundColor Green
Write-Host "Usuario Windows: $currentUser"
Write-Host "Frecuencia: cada 8 horas y al iniciar sesion"
Write-Host ""

# Ejecuta una primera consulta ahora.
Start-ScheduledTask -TaskName $taskName

Write-Host "Primera ejecucion solicitada."
Write-Host "Comprueba el resultado cuando termine."