# FLH-059: run the bounded E5 reproducibility diagnostic on the local CUDA GPU.
# It loads the prepared model files in this process (once per dtype), encodes
# the fixed matrix in inputs.json (456 positions per configuration, 6
# configurations) and writes results to -OutDir, which must be a new or empty
# directory OUTSIDE the repository. It never contacts the embedding service or
# any endpoint and changes nothing on the machine.
#
#   conda activate flh-embedding
#   .\scripts\validation\flh059\run-diagnostic.ps1 -ModelDir <prepared model dir> -OutDir <new dir outside the repo>
#
# Python source is never passed on the command line (see FLH-057); only file
# paths and fixed option values are passed as arguments.
param(
    [Parameter(Mandatory = $true)][string]$ModelDir,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Dtypes = 'float16,float32',
    [string]$Policies = 'dynamic_v1,singleton_v1,fixed_v1'
)
$ErrorActionPreference = 'Stop'
if ($env:CONDA_DEFAULT_ENV -ne 'flh-embedding') { throw "activate the Conda env first: conda activate flh-embedding" }
$ModelDir = (Resolve-Path -LiteralPath $ModelDir).Path
$OutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
$Script = Join-Path $PSScriptRoot 'diagnose.py'

Write-Output "powershell: $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition)"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed (exit $LASTEXITCODE)" }

python -B $Script run --model-dir $ModelDir --out $OutDir --dtypes $Dtypes --policies $Policies
$code = $LASTEXITCODE
if ($code -ne 0) { throw "diagnostic failed (exit $code); partial results, if any, are in $OutDir" }

nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv |
    Out-File -Encoding utf8 -LiteralPath (Join-Path $OutDir 'nvidia-smi-after.txt')
Get-ChildItem -LiteralPath $OutDir -File | Sort-Object Name | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), (Split-Path -Leaf $_.Path) } |
    Out-File -Encoding utf8 -LiteralPath (Join-Path $OutDir 'artifact-sha256.txt')
Write-Output "done: results and artifact-sha256.txt in $OutDir (keep them; do not copy vectors into the repository)"
