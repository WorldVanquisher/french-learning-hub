# FLH-054: record the environment before and after installing requirements.
# Read-only: installs nothing, downloads nothing. Run inside the activated
# Conda env:  conda activate flh-embedding ; .\tools\embedding\e5\windows\check-env.ps1
# FLH-057: the Python checks live in check_env.py next to this script. Python
# source is never passed as a native command argument (python -c $code), whose
# embedded double quotes Windows PowerShell 5.1 strips; only the file path is
# passed, and no model path or user text reaches Python source.
$ErrorActionPreference = 'Stop'
if ($env:CONDA_DEFAULT_ENV -ne 'flh-embedding') {
    Write-Warning "CONDA_DEFAULT_ENV is '$($env:CONDA_DEFAULT_ENV)', expected 'flh-embedding'."
}
Write-Output "powershell: $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition)"
Write-Output "python: $((Get-Command python).Source)"
python -m pip --version
if ($LASTEXITCODE -ne 0) { throw "pip --version failed (exit $LASTEXITCODE)" }
$CheckPy = Join-Path $PSScriptRoot 'check_env.py'
python -B $CheckPy
if ($LASTEXITCODE -ne 0) { throw "environment check failed (exit $LASTEXITCODE)" }
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed (exit $LASTEXITCODE)" }
