# FLH-054: start the service in THIS console (foreground; no background
# process, no autostart, no firewall change). Stop it with Ctrl+C.
# Default bind is 127.0.0.1. For NAS access pass the Windows machine's
# private IP explicitly, e.g. -BindHost 192.168.1.20 (the firewall/network
# profile must already allow it; this script changes nothing).
param(
    [Parameter(Mandatory = $true)][string]$ModelDir,
    [string]$BindHost = '127.0.0.1',
    [int]$Port = 8765,
    [ValidateSet('float16', 'float32')][string]$Dtype = 'float16',
    [int]$Microbatch = 8,
    # FLH-059: anything but dynamic_v1 is a new deployment identity (new index space).
    [ValidateSet('dynamic_v1', 'singleton_v1', 'fixed_v1')][string]$Batching = 'dynamic_v1'
)
$ErrorActionPreference = 'Stop'
if ($env:CONDA_DEFAULT_ENV -ne 'flh-embedding') { throw "activate the Conda env first: conda activate flh-embedding" }
$ModelDir = (Resolve-Path -LiteralPath $ModelDir).Path
$E5Root = Split-Path -Parent $PSScriptRoot
Push-Location $E5Root
try {
    Write-Output "PID $PID (PowerShell); the Python process is its child. Ctrl+C stops it."
    python -B -m flh_e5 serve --model-dir $ModelDir --host $BindHost --port $Port --dtype $Dtype --microbatch $Microbatch --batching $Batching
    Write-Output "service exited with code $LASTEXITCODE"
} finally { Pop-Location }
