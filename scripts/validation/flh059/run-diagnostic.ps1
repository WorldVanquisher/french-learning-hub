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
#
# -HashOnly (FLH-060) skips the GPU run and only writes artifact-sha256.txt for
# an existing results directory, e.g. one whose final hashing step failed:
#   .\scripts\validation\flh059\run-diagnostic.ps1 -OutDir <existing results dir> -HashOnly
# An existing artifact-sha256.txt is kept, renamed artifact-sha256.previous-<time>.txt.
param(
    [string]$ModelDir,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Dtypes = 'float16,float32',
    [string]$Policies = 'dynamic_v1,singleton_v1,fixed_v1',
    [switch]$HashOnly
)
$ErrorActionPreference = 'Stop'
$OutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
$Script = Join-Path $PSScriptRoot 'diagnose.py'
$HashList = 'artifact-sha256.txt'

if ($HashOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $OutDir 'analysis.json') -PathType Leaf)) {
        throw "-HashOnly needs an existing results directory containing analysis.json: $OutDir"
    }
} else {
    if (-not $ModelDir) { throw "-ModelDir is required unless -HashOnly is given" }
    if ($env:CONDA_DEFAULT_ENV -ne 'flh-embedding') { throw "activate the Conda env first: conda activate flh-embedding" }
    $ModelDir = (Resolve-Path -LiteralPath $ModelDir).Path

    Write-Output "powershell: $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition)"
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed (exit $LASTEXITCODE)" }

    python -B $Script run --model-dir $ModelDir --out $OutDir --dtypes $Dtypes --policies $Policies
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "diagnostic failed (exit $code); partial results, if any, are in $OutDir" }

    $smi = nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi after the run failed (exit $LASTEXITCODE); diagnostic results are kept in $OutDir" }
    $smi | Out-File -Encoding utf8 -LiteralPath (Join-Path $OutDir 'nvidia-smi-after.txt')
}

# FLH-060: enumerate and hash completely BEFORE writing the hash list, and never
# hash the list itself. (The FLH-059 version piped Get-ChildItem straight into
# Out-File, so the list being written was enumerated and hashed while open.)
# Any hashing failure throws: the run is reported as failed, and every result
# file stays in place.
$previous = Join-Path $OutDir $HashList
if (Test-Path -LiteralPath $previous) {
    $kept = "artifact-sha256.previous-$(Get-Date -Format yyyyMMdd-HHmmss).txt"
    Rename-Item -LiteralPath $previous -NewName $kept
    Write-Output "kept the earlier hash list as $kept (it is hashed below like any other file)"
}
$files = @(Get-ChildItem -LiteralPath $OutDir -File | Where-Object { $_.Name -ne $HashList } | Sort-Object Name)
if ($files.Count -eq 0) { throw "no result files to hash in $OutDir" }
$lines = @(foreach ($f in $files) {
    $h = Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName
    if (-not $h -or -not $h.Hash) { throw "could not hash $($f.Name); results are kept in $OutDir" }
    "{0}  {1}" -f $h.Hash.ToLowerInvariant(), $f.Name
})
if ($lines.Count -ne $files.Count) { throw "hashed $($lines.Count) of $($files.Count) files; results are kept in $OutDir" }
$lines | Out-File -Encoding utf8 -LiteralPath (Join-Path $OutDir $HashList)
Write-Output "done: $($lines.Count) result files hashed into $HashList in $OutDir (keep them; do not copy vectors into the repository)"
