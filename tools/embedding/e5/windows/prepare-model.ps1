# FLH-054: explicit, human-run preparation of the pinned model files.
# Without -Download it only prints what it would do. With -Download it fetches
# about 1.13 GB from huggingface.co into -ModelDir (pinned revision, the six
# files below only; no pytorch_model.bin, ONNX or OpenVINO files), then
# verifies every file against the digests pinned in flh_e5\manifest.py.
param(
    [Parameter(Mandatory = $true)][string]$ModelDir,
    [switch]$Download
)
$ErrorActionPreference = 'Stop'
$ModelDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ModelDir)
$Repo = 'intfloat/multilingual-e5-base'
$Revision = 'd128750597153bb5987e10b1c3493a34e5a4502a'
$Files = @('config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'sentencepiece.bpe.model')
$E5Root = Split-Path -Parent $PSScriptRoot
$cmd = @('download', $Repo) + $Files + @('--revision', $Revision, '--local-dir', $ModelDir)
Write-Output ("hf " + ($cmd -join ' '))
if (-not $Download) {
    Write-Output "Dry run. Re-run with -Download to fetch about 1.13 GB, then verify."
    exit 0
}
hf @cmd
if ($LASTEXITCODE -ne 0) { throw "hf download failed" }
Push-Location $E5Root
try {
    python -B -m flh_e5 verify-files --model-dir $ModelDir
    if ($LASTEXITCODE -ne 0) { throw "verification failed: do not use these files" }
} finally { Pop-Location }
