# FLH-054: stop a service whose console is no longer reachable. Prefer Ctrl+C
# in the service console (graceful: drains the running request, releases GPU
# memory, closes the listener). This lists matching python processes and, only
# with -Confirmed, stops them (process exit releases GPU memory and the port).
param([switch]$Confirmed)
$ErrorActionPreference = 'Stop'
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -match '-m flh_e5 serve' }
if (-not $procs) { Write-Output "no flh_e5 service process found"; exit 0 }
$procs | ForEach-Object { Write-Output ("PID {0}: {1}" -f $_.ProcessId, $_.CommandLine) }
if (-not $Confirmed) { Write-Output "Re-run with -Confirmed to stop the processes above."; exit 0 }
$procs | ForEach-Object { Stop-Process -Id $_.ProcessId }
Write-Output "stopped; check: nvidia-smi and Test-NetConnection -ComputerName <host> -Port <port>"
