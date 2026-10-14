<#
.SYNOPSIS
FLH-065 operator entry point for the detached Windows E5 embedding service.

.DESCRIPTION
Windows PowerShell 5.1 compatible. Actions:
  check          read-only preflight (paths, Conda env, port, Tailscale);
                 -VerifyFiles hashes the model files, -Cuda runs check_env.py
  start          launch detached (survives the SSH session) and wait, bounded,
                 for readiness with the expected deployment identity
  status         process state and model state, separately (-Json available)
  stop           graceful stop of this launcher's own run (-Force: no grace)
  logs           tail a run's logs (-Stream stderr|stdout|runner|all, -Tail N,
                 -Run <id>|latest, -List)
  serve-status   show Tailscale Serve forwards (read-only)
  serve-enable   reuse a matching forward, or add one explicitly (persistent)
  serve-disable  remove only a forward this tool recorded adding

The service always listens on 127.0.0.1 and runs float16, microbatch 8,
singleton_v1 batching. Exit codes are listed in
docs/WINDOWS_EMBEDDING_OPERATIONS.md.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File flh-e5.ps1 start
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('check', 'start', 'status', 'stop', 'logs', 'serve-status', 'serve-enable', 'serve-disable')]
    [string]$Action,
    [string]$RuntimeDir,
    [string]$E5Dir,
    [string]$ModelDir,
    [string]$CondaEnvName,
    [string]$CondaPrefix,
    [string]$PythonExe,
    [string]$StateDir,
    [int]$Port,
    [string]$ExpectedDeploymentId,
    [int]$ReadyTimeoutSec,
    [int]$GracefulTimeoutSec,
    [int]$KeepRuns,
    [int]$ServePort,
    [string]$Run,
    [ValidateSet('stderr', 'stdout', 'runner', 'all')]
    [string]$Stream,
    [int]$Tail,
    [switch]$List,
    [switch]$Json,
    [switch]$Force,
    [switch]$VerifyFiles,
    [switch]$Cuda
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'FlhE5Ops.psm1') -Force
$bound = @{}
foreach ($k in $PSBoundParameters.Keys) { if ($k -ne 'Action') { $bound[$k] = $PSBoundParameters[$k] } }
try {
    [int]$code = Invoke-FlhAction -Action $Action -Bound $bound
} catch {
    Write-Host ("error: {0}" -f $_.Exception.Message)
    $code = 1
}
exit $code
