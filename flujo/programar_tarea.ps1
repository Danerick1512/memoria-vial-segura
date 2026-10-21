# Registra la ejecución diaria del flujo en el Programador de tareas de Windows.
# Uso (PowerShell):  .\flujo\programar_tarea.ps1 -Hora "06:00"
#   Quitar:          Unregister-ScheduledTask -TaskName "MemoriaVialSegura-Diario" -Confirm:$false
param(
    [string]$Hora = "06:00",
    [string]$Nombre = "MemoriaVialSegura-Diario"
)
$raiz = Split-Path -Parent $PSScriptRoot
$python = Join-Path $raiz ".venv\Scripts\python.exe"
$script = Join-Path $raiz "flujo\run_daily.py"
if (-not (Test-Path $python)) { throw "No existe $python. Crea primero el entorno: py -3.11 -m venv .venv" }

$accion = New-ScheduledTaskAction -Execute $python -Argument "`"$script`" --hoy" -WorkingDirectory $raiz
$disparador = New-ScheduledTaskTrigger -Daily -At $Hora
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger $disparador -Settings $ajustes `
    -Description "Memoria Vial Segura: reportes del día -> PLN -> grafo -> boletín" -Force | Out-Null
Write-Host "Tarea '$Nombre' registrada: todos los días a las $Hora ejecuta $script --hoy"
