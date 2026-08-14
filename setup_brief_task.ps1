# Registra la tarea programada del Brief semanal de Direccion.
# Ejecutar UNA vez, en PowerShell como administrador, parado en worms_supabase:
#     powershell -ExecutionPolicy Bypass -File .\setup_brief_task.ps1
param(
    [string]$Hora = "07:30",                 # hora local del lunes
    [string]$Nombre = "WORMS Brief Direccion"
)
$bat = Join-Path $PSScriptRoot "brief_semanal.bat"
if (-not (Test-Path $bat)) { throw "No encuentro $bat" }

$accion  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$disparo = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $Hora
$config  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger $disparo `
    -Settings $config -Description "Genera y envia el brief semanal de direccion (semana ISO cerrada)." -Force

Write-Host "Tarea '$Nombre' registrada: todos los lunes a las $Hora."
Write-Host "Probala ya con:  Start-ScheduledTask -TaskName '$Nombre'"
