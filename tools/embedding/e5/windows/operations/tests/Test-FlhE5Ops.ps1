<#
FLH-065 tests for flh-e5.ps1 / FlhE5Ops.psm1. Dependency-free (no Pester).

Runs on macOS/Linux with PowerShell 7 against the POSIX test platform and the
fake flh_e5 service (tests/fake_e5): no model, no GPU, no WMI. Every lifecycle
action is a separate pwsh process, like separate SSH commands. The Windows
platform (WMI, Get-NetTCPConnection) is NOT exercised here.

  pwsh -NoProfile -File tools/embedding/e5/windows/operations/tests/Test-FlhE5Ops.ps1 [-Python python3] [-Port 18765]

Exit 0 when every test passes.
#>
param([string]$Python = 'python3', [int]$Port = 18765)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Ops = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Ops 'flh-e5.ps1'
$FakeE5 = Join-Path $PSScriptRoot 'fake_e5'
Import-Module (Join-Path $Ops 'FlhE5Ops.psm1') -Force
$Pwsh = (Get-Process -Id $PID).Path
$PyExe = (& $Python -c 'import sys; print(sys.executable)').Trim()
$PyPrefix = Split-Path -Parent (Split-Path -Parent $PyExe)
$Root = Join-Path ([System.IO.Path]::GetTempPath()) ("flh065 tests " + [guid]::NewGuid().ToString('N').Substring(0, 6))
$null = New-Item -ItemType Directory -Path $Root
$script:Failures = 0
$script:Passed = 0
$script:Spawned = @()

function Check([bool]$Cond, [string]$What) {
    if ($Cond) { $script:Passed++; Write-Host "  ok    $What" } else { $script:Failures++; Write-Host "  FAIL  $What" }
}

function New-Case([string]$Name, [string]$Mode = 'ready') {
    $dir = Join-Path $Root $Name
    $model = Join-Path $dir 'model dir with spaces'
    $null = New-Item -ItemType Directory -Path $model -Force
    foreach ($f in @('config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'sentencepiece.bpe.model')) {
        $null = New-Item -ItemType File -Path (Join-Path $model $f) -Force
    }
    Set-Content -LiteralPath (Join-Path $model 'FAKE_MODE') -Value $Mode
    $state = Join-Path $dir 'state dir'
    return @{ Dir = $dir; Model = $model; State = $state
        Args = @('-E5Dir', $FakeE5, '-ModelDir', $model, '-PythonExe', $PyExe, '-CondaPrefix', $PyPrefix,
                 '-StateDir', $state, '-Port', [string]$Port, '-ReadyTimeoutSec', '20', '-GracefulTimeoutSec', '5') }
}

function Set-Arg([string[]]$Arguments, [string]$Name, [string]$Value) {
    # replace a parameter's value (pwsh rejects a repeated parameter)
    $a = @($Arguments)
    $i = [array]::IndexOf($a, $Name)
    if ($i -ge 0) { $a[$i + 1] = $Value; return , $a }
    return , ($a + @($Name, $Value))
}

function Ops([string]$Action, [string[]]$Arguments) {
    $out = & $Pwsh -NoProfile -File $Entry $Action @Arguments 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}

function Get-Listeners { return @(& lsof -nP ("-iTCP:{0}" -f $Port) -sTCP:LISTEN -t 2>$null) }
function Test-Alive([int]$Id) { & ps -p $Id *> $null; return ($LASTEXITCODE -eq 0) }

function Start-Unrelated([string[]]$Arguments) {
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = $PyExe
    $si.Arguments = Join-FlhCommandLine $Arguments
    $si.UseShellExecute = $false
    $si.RedirectStandardError = $true
    $si.RedirectStandardOutput = $true
    $p = [System.Diagnostics.Process]::Start($si)
    $script:Spawned += $p
    Start-Sleep -Milliseconds 800
    return $p
}

try {
    Write-Host "T1 quoting round trip through real process creation"
    $values = @('plain', 'with space', 'C:\Program Files\x\', 'quote"inside', 'back\\slash\"q', '', "tab`tx", ('{0} accent' -f [char]0xE9), 'trail\\', 'a b\c d\')
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = $PyExe
    $si.Arguments = (Join-FlhCommandLine @('-c', 'import json,sys; print(json.dumps(sys.argv[1:]))')) + ' ' + (Join-FlhCommandLine $values)
    $si.UseShellExecute = $false
    $si.RedirectStandardOutput = $true
    $p = [System.Diagnostics.Process]::Start($si)
    $got = $p.StandardOutput.ReadToEnd() | ConvertFrom-Json
    $p.WaitForExit()
    Check ($got.Count -eq $values.Count) "argument count preserved ($($values.Count))"
    $same = $true
    for ($i = 0; $i -lt $values.Count; $i++) { if ($got[$i] -cne $values[$i]) { $same = $false; Write-Host "    mismatch [$i]: <$($values[$i])> -> <$($got[$i])>" } }
    Check $same 'every argument round-trips exactly (spaces, quotes, backslashes, empty, tab, non-ASCII)'

    Write-Host "T2 lifecycle: start, idempotent start, status, stop, idempotent stop (paths with spaces)"
    $c = New-Case 'lifecycle'
    $r = Ops 'start' $c.Args
    Check ($r.Code -eq 0) "start exit 0 (got $($r.Code))"
    Check ($r.Out -match 'ready: deployment_id .*singleton_v1/5a3e23f28a05baff') 'start reports the expected identity'
    $cur = Get-Content -LiteralPath (Join-Path $c.State 'current.json') -Raw | ConvertFrom-Json
    $child1 = $cur.child.pid
    $argv = Get-Content -LiteralPath (Join-Path $c.Model 'argv.log') | Select-Object -Last 1 | ConvertFrom-Json
    Check ($argv[3] -ceq $c.Model) 'the service received the model path with spaces as one argument'
    $r = Ops 'start' $c.Args
    $cur2 = Get-Content -LiteralPath (Join-Path $c.State 'current.json') -Raw | ConvertFrom-Json
    Check ($r.Code -eq 0 -and $r.Out -match 'already running' -and $cur2.child.pid -eq $child1) 'second start reuses the running service'
    $r = Ops 'status' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'status: ready') 'status exit 0 ready'
    $r = Ops 'stop' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'stop_requested_graceful') "graceful stop (got $($r.Code))"
    Check (-not (Test-Alive $child1)) 'service process gone'
    Check (@(Get-Listeners).Count -eq 0) 'port free after stop'
    $r = Ops 'stop' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'not running') 'second stop is a no-op'
    $r = Ops 'status' $c.Args
    Check ($r.Code -eq 3) "status exit 3 when stopped (got $($r.Code))"
    $r = Ops 'start' $c.Args
    $r2 = Ops 'stop' $c.Args
    Check ($r.Code -eq 0 -and $r2.Code -eq 0) 'start/stop again after a full cycle'
    $runs = @(Get-ChildItem -LiteralPath (Join-Path $c.State 'runs') -Directory)
    Check (@($runs | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'final.json') }).Count -eq 2) 'each run keeps final.json and its logs'

    Write-Host "T3 unrelated process on the port"
    $c = New-Case 'occupied'
    $u = Start-Unrelated @('-m', 'http.server', [string]$Port, '--bind', '127.0.0.1')
    $r = Ops 'start' $c.Args
    Check ($r.Code -eq 2 -and $r.Out -match 'refused: port') "start refused with exit 2 (got $($r.Code))"
    Check (-not (Test-Path -LiteralPath (Join-Path $c.State 'current.json'))) 'nothing launched or recorded'
    $r = Ops 'stop' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'not touched') 'stop leaves the unrelated listener alone'
    $r = Ops 'status' $c.Args
    Check ($r.Code -eq 1 -and $r.Out -match 'another process') "status exit 1 for an unrelated listener (got $($r.Code))"
    Check (-not $u.HasExited) 'unrelated process still running'
    $u.Kill(); $u.WaitForExit()

    Write-Host "T4 another flh_e5 service on a different port"
    $c = New-Case 'other-encoder'
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = $PyExe
    $si.Arguments = Join-FlhCommandLine @('-B', '-m', 'flh_e5', 'serve', '--model-dir', $c.Model, '--port', [string]($Port + 1))
    $si.WorkingDirectory = $FakeE5
    $si.UseShellExecute = $false
    $si.RedirectStandardError = $true
    $si.RedirectStandardOutput = $true
    $other = [System.Diagnostics.Process]::Start($si)
    $script:Spawned += $other
    Start-Sleep -Milliseconds 800
    $r = Ops 'start' $c.Args
    Check ($r.Code -eq 2 -and $r.Out -match 'another flh_e5 service') "start refused while another encoder runs (got $($r.Code))"
    Check (-not $other.HasExited) 'the other encoder is untouched'
    $other.Kill(); $other.WaitForExit()

    Write-Host "T5 refusals: missing model/runtime, bad paths"
    $c = New-Case 'refusals'
    Remove-Item -LiteralPath (Join-Path $c.Model 'model.safetensors')
    $r = Ops 'start' $c.Args
    Check ($r.Code -eq 2 -and $r.Out -match 'missing: model.safetensors') 'missing model file -> exit 2'
    $null = New-Item -ItemType File -Path (Join-Path $c.Model 'model.safetensors')
    $a = @($c.Args); $a[3] = (Join-Path $c.Dir 'no such model')
    $r = Ops 'start' $a
    Check ($r.Code -eq 2 -and $r.Out -match 'does not exist') 'missing model dir -> exit 2'
    $a = @($c.Args); $a[5] = (Join-Path $c.Dir 'no-python')
    $r = Ops 'start' $a
    Check ($r.Code -eq 2 -and $r.Out -match 'PythonExe') 'missing python -> exit 2'
    $a = @($c.Args); $a[1] = $c.Dir
    $r = Ops 'start' $a
    Check ($r.Code -eq 2 -and $r.Out -match 'no flh_e5 package') 'E5 dir without flh_e5 -> exit 2'
    $a = @($c.Args); $a[3] = 'relative/model'
    $r = Ops 'start' $a
    Check ($r.Code -eq 2 -and $r.Out -match 'absolute') 'relative path -> exit 2'
    $a = @($c.Args); $a[3] = ($c.Dir + '/bad"quote')
    $r = Ops 'start' $a
    Check ($r.Code -eq 2 -and $r.Out -match 'double quote') 'path with a double quote -> exit 2'
    $a = Set-Arg $c.Args '-Port' '80'
    $r = Ops 'start' $a
    Check ($r.Code -eq 2) 'port below 1024 -> exit 2'
    $r = Ops 'logs' (@($c.Args) + @('-Tail', '0'))
    Check ($r.Code -eq 2) 'logs -Tail 0 -> exit 2'
    Check (@(Get-Listeners).Count -eq 0) 'nothing listening after refusals'

    Write-Host "T6 startup failure"
    $c = New-Case 'fail' 'fail'
    $r = Ops 'start' $c.Args
    Check ($r.Code -eq 1 -and $r.Out -match 'startup failed: the service exited \(exit code 3\)') "startup failure -> exit 1 with the exit code (got $($r.Code))"
    Check ($r.Out -match 'stderr: .*startup failed, not ready') 'stderr tail shown'
    Check (-not (Test-Path -LiteralPath (Join-Path $c.State 'current.json'))) 'record archived'
    $r = Ops 'logs' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'fake failure') 'logs show the failure afterwards'

    Write-Host "T7 identity mismatch"
    $c = New-Case 'mismatch' 'mismatch'
    $r = Ops 'start' $c.Args
    Check ($r.Code -eq 1 -and $r.Out -match 'expected') "mismatch -> exit 1 (got $($r.Code))"
    Check (@(Get-Listeners).Count -eq 0) 'the mismatched run was stopped'
    Check (@(& ps -axww -o command= | Where-Object { $_ -match 'flh_e5 serve' -and $_ -match [regex]::Escape($c.Model) }).Count -eq 0) 'no leftover service process'

    Write-Host "T8 forced stop after the graceful timeout"
    $c = New-Case 'forced' 'ignore-signals'
    $a = Set-Arg $c.Args '-GracefulTimeoutSec' '2'
    $r = Ops 'start' $a
    $r = Ops 'stop' $a
    Check ($r.Code -eq 0 -and $r.Out -match 'stop_requested_forced') "forced after timeout (got $($r.Code))"
    Check (@(Get-Listeners).Count -eq 0) 'port free'

    Write-Host "T9 not ready within the timeout"
    $c = New-Case 'slow' 'never-ready'
    $a = Set-Arg $c.Args '-ReadyTimeoutSec' '3'
    $r = Ops 'start' $a
    Check ($r.Code -eq 4 -and $r.Out -match 'left running') "timeout -> exit 4 (got $($r.Code))"
    $r = Ops 'status' $a
    Check ($r.Code -eq 4 -and $r.Out -match 'model not ready') 'status distinguishes running from ready (exit 4)'
    $r = Ops 'stop' $a
    Check ($r.Code -eq 0) 'stop'

    Write-Host "T10 supervisor killed: stop terminates the proven-owned orphan only"
    $c = New-Case 'orphan'
    $r = Ops 'start' $c.Args
    $cur = Get-Content -LiteralPath (Join-Path $c.State 'current.json') -Raw | ConvertFrom-Json
    & kill -9 $cur.runner.pid
    Start-Sleep -Milliseconds 500
    $r = Ops 'stop' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'terminating the service PID') "orphan service terminated (got $($r.Code))"
    Check (-not (Test-Alive $cur.child.pid)) 'orphan gone'

    Write-Host "T11 PID reuse: a forged record never kills an unrelated process"
    $c = New-Case 'pidreuse'
    $victim = Start-Unrelated @('-c', 'import time; time.sleep(60)')
    $null = New-Item -ItemType Directory -Force -Path (Join-Path $c.State 'runs')
    $forged = [ordered]@{ schema = 'flh065_e5_current_v1'; run_id = '20200101T000000Z-deadbeef'; run_dir = (Join-Path $c.State 'runs/20200101T000000Z-deadbeef')
        spec_path = (Join-Path $c.State 'runs/20200101T000000Z-deadbeef/launch.json'); port = $Port; expected_deployment_id = 'x'
        runner = [ordered]@{ pid = $victim.Id; created = 'Mon Jan  1 00:00:00 2001' }; child = [ordered]@{ pid = $victim.Id; created = 'Mon Jan  1 00:00:00 2001' } }
    Set-Content -LiteralPath (Join-Path $c.State 'current.json') -Value ($forged | ConvertTo-Json -Depth 5)
    $r = Ops 'stop' $c.Args
    Check ($r.Code -eq 0 -and $r.Out -match 'unrelated process; not touched') 'stop reports the PID as unrelated'
    Check (-not $victim.HasExited) 'unrelated process still alive'
    $victim.Kill(); $victim.WaitForExit()

    Write-Host "T12 retention keeps the newest runs and only touches run directories"
    $c = New-Case 'retention'
    $runsDir = Join-Path $c.State 'runs'
    $null = New-Item -ItemType Directory -Force -Path $runsDir
    for ($i = 10; $i -lt 22; $i++) { $null = New-Item -ItemType Directory -Path (Join-Path $runsDir ("202001{0:D2}T000000Z-0000aaaa" -f $i)) }
    $null = New-Item -ItemType Directory -Path (Join-Path $runsDir 'operator notes')
    $a = @($c.Args) + @('-KeepRuns', '3')
    $r = Ops 'start' $a
    $left = @(Get-ChildItem -LiteralPath $runsDir -Directory | Where-Object { $_.Name -match '^\d{8}T\d{6}Z-[0-9a-f]{8}$' })
    Check ($left.Count -eq 3) "3 run directories kept (got $($left.Count))"
    Check (Test-Path -LiteralPath (Join-Path $runsDir 'operator notes')) 'unrelated directory untouched'
    $r = Ops 'logs' (@($a) + @('-List'))
    Check ($r.Code -eq 0 -and ($r.Out -split "`n" | Where-Object { $_ -match '^\d{8}T' }).Count -eq 3) 'logs -List shows the runs'
    $r = Ops 'stop' $a

    Write-Host "T13 Tailscale Serve decisions (fake tailscale)"
    $ts = @{ Config = '{}'; Calls = New-Object System.Collections.ArrayList }
    $plat = Get-FlhPosixPlatform
    $plat.Tailscale = {
        param([string[]]$Arguments)
        [void]$ts.Calls.Add(($Arguments -join ' '))
        $j = $Arguments -join ' '
        if ($j -eq 'serve status --json') { return @{ ExitCode = 0; Output = $ts.Config } }
        if ($j -like 'serve --bg --http=*') {
            $sp = ($Arguments[2] -replace '--http=', '')
            $cfg = $ts.Config | ConvertFrom-Json
            if ($null -eq $cfg -or $null -eq $cfg.PSObject.Properties['Web']) { $cfg = [pscustomobject]@{ TCP = [pscustomobject]@{}; Web = [pscustomobject]@{} } }
            $cfg.TCP | Add-Member -NotePropertyName $sp -NotePropertyValue ([pscustomobject]@{ HTTP = $true }) -Force
            $cfg.Web | Add-Member -NotePropertyName ("host.tail-x.ts.net:" + $sp) -NotePropertyValue ([pscustomobject]@{ Handlers = [pscustomobject]@{ '/' = [pscustomobject]@{ Proxy = $Arguments[3] } } }) -Force
            $ts.Config = $cfg | ConvertTo-Json -Depth 8
            return @{ ExitCode = 0; Output = '' }
        }
        if ($j -like 'serve --http=* off') {
            $sp = ($Arguments[1] -replace '--http=', '')
            $cfg = $ts.Config | ConvertFrom-Json
            $cfg.TCP.PSObject.Properties.Remove($sp)
            $cfg.Web.PSObject.Properties.Remove("host.tail-x.ts.net:" + $sp)
            $ts.Config = $cfg | ConvertTo-Json -Depth 8
            return @{ ExitCode = 0; Output = '' }
        }
        return @{ ExitCode = 0; Output = 'fake' }
    }.GetNewClosure()
    $sc = New-Case 'serve'
    $b = @{ StateDir = $sc.State; Port = $Port }
    $unrelated = '{"TCP":{"443":{"HTTPS":true}},"Web":{"host.tail-x.ts.net:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:3000"}}}}}'
    $ts.Config = $unrelated
    $code = Invoke-FlhAction -Action 'serve-enable' -Bound $b -Platform $plat
    Check ($code -eq 0 -and $ts.Calls -contains "serve --bg --http=8765 http://127.0.0.1:$Port") 'enable adds exactly one explicit forward'
    Check (-not ($ts.Calls | Where-Object { $_ -match 'reset|funnel' })) 'never reset or funnel'
    $cfg = $ts.Config | ConvertFrom-Json
    Check ($null -ne $cfg.Web.PSObject.Properties['host.tail-x.ts.net:443']) 'unrelated forward preserved'
    $ts.Calls.Clear()
    $code = Invoke-FlhAction -Action 'serve-enable' -Bound $b -Platform $plat
    Check ($code -eq 0 -and -not ($ts.Calls | Where-Object { $_ -like 'serve --bg*' })) 'second enable reuses it, no change'
    $code = Invoke-FlhAction -Action 'serve-disable' -Bound $b -Platform $plat
    $cfg = $ts.Config | ConvertFrom-Json
    Check ($code -eq 0 -and $ts.Calls -contains 'serve --http=8765 off' -and $null -eq $cfg.Web.PSObject.Properties['host.tail-x.ts.net:8765']) 'disable removes only the recorded forward'
    Check ($null -ne $cfg.Web.PSObject.Properties['host.tail-x.ts.net:443']) 'unrelated forward still preserved'
    $ts.Calls.Clear()
    $ts.Config = '{"TCP":{"8765":{"HTTP":true}},"Web":{"host.tail-x.ts.net:8765":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:' + $Port + '"}}}}}'
    $code = Invoke-FlhAction -Action 'serve-enable' -Bound $b -Platform $plat
    Check ($code -eq 0 -and $ts.Calls.Count -eq 1) 'pre-existing matching forward reused (status only)'
    $code = Invoke-FlhAction -Action 'serve-disable' -Bound $b -Platform $plat
    Check ($code -eq 0 -and -not ($ts.Calls | Where-Object { $_ -like '*off' })) 'disable never removes a forward it did not add'
    $ts.Calls.Clear()
    $ts.Config = '{"TCP":{"8765":{"HTTP":true}},"Web":{"host.tail-x.ts.net:8765":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:9999"}}}}}'
    $code = Invoke-FlhAction -Action 'serve-enable' -Bound $b -Platform $plat
    Check ($code -eq 2 -and $ts.Calls.Count -eq 1) 'port carrying another target -> refused, no change'
    $ts.Calls.Clear()
    $ts.Config = '{"AllowFunnel":{"host.tail-x.ts.net:443":true}}'
    $code = Invoke-FlhAction -Action 'serve-enable' -Bound $b -Platform $plat
    Check ($code -eq 2 -and $ts.Calls.Count -eq 1) 'Funnel enabled -> refused'
    $fw = Get-FlhServeForwards -Config ('{"Foreground":{"abc":{"TCP":{"8765":{"HTTP":true}},"Web":{"h:8765":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8765"}}}}}}}' | ConvertFrom-Json)
    Check (@($fw | Where-Object { $_.Scope -like 'foreground*' -and $_.Target -eq 'http://127.0.0.1:8765' }).Count -eq 1) 'foreground session forwards are parsed'
    Check ((Test-FlhServeTarget 'http://localhost:8765/' 8765) -and -not (Test-FlhServeTarget 'http://127.0.0.1:87650' 8765)) 'target matching is exact'

    Write-Host "T14 PowerShell parse of every operations script"
    foreach ($f in @(Get-ChildItem -LiteralPath $Ops -Recurse -Include '*.ps1', '*.psm1')) {
        $tokens = $null; $errs = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errs)
        Check ($errs.Count -eq 0) ("parses: " + $f.Name)
    }
} finally {
    foreach ($p in $script:Spawned) { try { if (-not $p.HasExited) { $p.Kill() } } catch { } }
    # stop anything a failed test left running from these state directories
    foreach ($d in @(Get-ChildItem -LiteralPath $Root -Directory)) {
        $st = Join-Path $d.FullName 'state dir'
        if (Test-Path -LiteralPath (Join-Path $st 'current.json')) { $null = Ops 'stop' @('-StateDir', $st, '-Port', [string]$Port, '-GracefulTimeoutSec', '2') }
    }
    Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host ("{0} passed, {1} failed" -f $script:Passed, $script:Failures)
if ($script:Failures -gt 0) { exit 1 }
exit 0
