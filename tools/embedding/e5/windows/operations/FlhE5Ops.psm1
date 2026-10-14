# FLH-065: operations for the detached Windows E5 embedding service.
#
# Windows PowerShell 5.1 compatible (also runs under PowerShell 7). All
# decisions live here; process, listener and launch operations come from an
# injected "platform" table so the logic is testable off Windows. The Windows
# platform uses WMI (Win32_Process.Create) to start the supervisor outside the
# SSH session's job object. The POSIX platform exists only for local tests.
#
# Actions return an exit code (see Invoke-FlhAction). Nothing here kills a
# process by name: only a process whose PID, creation time and command line
# match this launcher's own record is ever signalled or terminated.

Set-StrictMode -Version 2.0

$script:DefaultDeploymentId = 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff'
$script:ModelFiles = @('config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'sentencepiece.bpe.model')
$script:RunIdPattern = '^\d{8}T\d{6}Z-[0-9a-f]{8}$'
$script:ServeArgsFixed = @('--dtype', 'float16', '--microbatch', '8', '--batching', 'singleton_v1')
$script:ModuleDir = $PSScriptRoot
$script:Quiet = $false

function Write-FlhLine {
    param([string]$Text = '')
    if (-not $script:Quiet) { Write-Host $Text }
}

function Test-FlhIsWindows {
    $v = Get-Variable -Name IsWindows -Scope Global -ErrorAction SilentlyContinue
    if ($null -eq $v) { return $true }   # Windows PowerShell 5.1 has no $IsWindows
    return [bool]$v.Value
}

function Get-FlhProp {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Get-FlhUtcNow { [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'") }

# ---------------------------------------------------------------- quoting

function ConvertTo-FlhArgument {
    # One argument quoted for CommandLineToArgvW / the MS C runtime parser.
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq [char]'\') { $slashes++; continue }
        if ($ch -eq [char]'"') {
            [void]$sb.Append([char]'\', (2 * $slashes + 1))
            [void]$sb.Append([char]'"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) { [void]$sb.Append([char]'\', $slashes); $slashes = 0 }
        [void]$sb.Append($ch)
    }
    if ($slashes -gt 0) { [void]$sb.Append([char]'\', (2 * $slashes)) }
    [void]$sb.Append([char]'"')
    return $sb.ToString()
}

function Join-FlhCommandLine {
    param([string[]]$Arguments)
    $parts = @()
    foreach ($a in $Arguments) { $parts += (ConvertTo-FlhArgument $a) }
    return ($parts -join ' ')
}

# ---------------------------------------------------------------- JSON files

function Read-FlhJson {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
        return ($text | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Write-FlhJson {
    # Atomic replace; UTF-8 without BOM.
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 8
    $tmp = $Path + '.tmp'
    [System.IO.File]::WriteAllText($tmp, $json + "`n", (New-Object System.Text.UTF8Encoding $false))
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        [System.IO.File]::Replace($tmp, $Path, [NullString]::Value)   # a bare $null would become ""
    } else {
        [System.IO.File]::Move($tmp, $Path)
    }
}

# ---------------------------------------------------------------- HTTP

function Invoke-FlhHttpGet {
    # Bounded GET without a proxy. Returns @{Status; Body; Error}; Status 0 = no answer.
    param([string]$Url, [int]$TimeoutSec = 3)
    $req = [System.Net.WebRequest]::Create($Url)
    $req.Method = 'GET'
    $req.Proxy = $null
    $req.Timeout = $TimeoutSec * 1000
    $req.ReadWriteTimeout = $TimeoutSec * 1000
    $resp = $null
    try {
        try {
            $resp = $req.GetResponse()
        } catch [System.Net.WebException] {
            $resp = $_.Exception.Response
            if ($null -eq $resp) { return @{ Status = 0; Body = $null; Error = $_.Exception.Message } }
        }
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $body = $reader.ReadToEnd()
        $reader.Close()
        return @{ Status = [int]$resp.StatusCode; Body = $body; Error = $null }
    } catch {
        return @{ Status = 0; Body = $null; Error = $_.Exception.Message }
    } finally {
        if ($null -ne $resp) { $resp.Close() }
    }
}

# ---------------------------------------------------------------- platforms

function Get-FlhWindowsPlatform {
    $p = @{}
    $p.Name = 'windows'
    $p.GetProcess = {
        param([int]$Id)
        $w = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId = {0}" -f $Id) -ErrorAction SilentlyContinue
        if ($null -eq $w) { return $null }
        $created = $null
        if ($null -ne $w.CreationDate) { $created = $w.CreationDate.ToUniversalTime().ToString('o') }
        return [pscustomobject]@{ Id = [int]$w.ProcessId; ParentId = [int]$w.ParentProcessId; Name = [string]$w.Name
            CommandLine = [string]$w.CommandLine; Created = $created }
    }
    $p.ListEncoderProcesses = {
        $all = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue)
        $out = @()
        foreach ($w in $all) {
            if ([string]$w.CommandLine -match '-m\s+flh_e5\s+serve') {
                $out += [pscustomobject]@{ Id = [int]$w.ProcessId; CommandLine = [string]$w.CommandLine }
            }
        }
        return , $out
    }
    $p.GetListenerPids = {
        param([int]$Port)
        $pids = @()
        if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
            $pids = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.OwningProcess })
        } else {
            foreach ($line in (netstat -ano -p TCP) + (netstat -ano -p TCPv6)) {
                if ($line -match ('^\s*TCP\s+\S+:{0}\s+\S+\s+LISTENING\s+(\d+)\s*$' -f $Port)) { $pids += [int]$Matches[1] }
            }
        }
        return , @($pids | Sort-Object -Unique)
    }
    $p.StartDetached = {
        param([string]$FilePath, [string]$Arguments, [string]$WorkingDirectory)
        $class = Get-CimClass -ClassName Win32_ProcessStartup
        $startup = New-CimInstance -CimClass $class -ClientOnly -Property @{ ShowWindow = [uint16]0 }
        $cmd = (ConvertTo-FlhArgument $FilePath) + ' ' + $Arguments
        $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine = $cmd; CurrentDirectory = $WorkingDirectory; ProcessStartupInformation = $startup }
        if ($r.ReturnValue -ne 0) { throw ("Win32_Process.Create returned {0}" -f $r.ReturnValue) }
        return [int]$r.ProcessId
    }
    $p.KillProcess = { param([int]$Id) Stop-Process -Id $Id -Force -ErrorAction Stop }
    $p.HttpGet = { param([string]$Url, [int]$TimeoutSec) Invoke-FlhHttpGet -Url $Url -TimeoutSec $TimeoutSec }
    $p.Tailscale = {
        param([string[]]$Arguments)
        $exe = $null
        $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { $exe = $cmd.Source }
        elseif ($env:ProgramFiles -and (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'))) {
            $exe = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
        }
        if ($null -eq $exe) { return @{ ExitCode = 127; Output = 'tailscale.exe not found (PATH or %ProgramFiles%\Tailscale)'; Exe = $null } }
        $out = & $exe @Arguments 2>&1 | Out-String
        return @{ ExitCode = $LASTEXITCODE; Output = $out; Exe = $exe }
    }
    return $p
}

function Get-FlhPosixPlatform {
    # Local test platform (macOS/Linux): ps, lsof and .NET process start.
    $p = @{}
    $p.Name = 'posix'
    $p.GetProcess = {
        param([int]$Id)
        $ppid = (& ps -o ppid= -p $Id 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $ppid -eq '') { return $null }
        $stat = (& ps -o stat= -p $Id 2>$null | Out-String).Trim()
        if ($stat -like 'Z*') { return $null }   # an exited child not yet reaped
        $lstart = (& ps -o lstart= -p $Id 2>$null | Out-String).Trim()
        $cmdline = (& ps -o command= -ww -p $Id 2>$null | Out-String).Trim()
        return [pscustomobject]@{ Id = $Id; ParentId = [int]$ppid; Name = ''; CommandLine = $cmdline; Created = $lstart }
    }
    $p.ListEncoderProcesses = {
        $out = @()
        foreach ($line in (& ps -axww -o pid=,command= 2>$null)) {
            if ($line -match '^\s*(\d+)\s+(.*)$' -and $Matches[2] -match '-m\s+flh_e5\s+serve' -and $Matches[2] -notmatch '\bps\b') {
                $out += [pscustomobject]@{ Id = [int]$Matches[1]; CommandLine = $Matches[2] }
            }
        }
        return , $out
    }
    $p.GetListenerPids = {
        param([int]$Port)
        $pids = @(& lsof -nP ("-iTCP:{0}" -f $Port) -sTCP:LISTEN -t 2>$null | ForEach-Object { [int]$_ })
        return , @($pids | Sort-Object -Unique)
    }
    $p.StartDetached = {
        param([string]$FilePath, [string]$Arguments, [string]$WorkingDirectory)
        # Detach stdio through sh (like WMI, the caller's pipes must not be
        # inherited); $Arguments is still parsed with the Windows rules by .NET.
        $si = New-Object System.Diagnostics.ProcessStartInfo
        $si.FileName = '/bin/sh'
        $si.Arguments = (Join-FlhCommandLine @('-c', 'exec "$@" </dev/null >/dev/null 2>&1', 'sh', $FilePath)) + ' ' + $Arguments
        $si.WorkingDirectory = $WorkingDirectory
        $si.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($si)
        return [int]$proc.Id
    }
    $p.KillProcess = { param([int]$Id) & kill -9 $Id }
    $p.HttpGet = { param([string]$Url, [int]$TimeoutSec) Invoke-FlhHttpGet -Url $Url -TimeoutSec $TimeoutSec }
    $p.Tailscale = {
        param([string[]]$Arguments)
        $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
        if ($null -eq $cmd) { return @{ ExitCode = 127; Output = 'tailscale not found'; Exe = $null } }
        $out = & $cmd.Source @Arguments 2>&1 | Out-String
        return @{ ExitCode = $LASTEXITCODE; Output = $out; Exe = $cmd.Source }
    }
    return $p
}

function Get-FlhDefaultPlatform {
    if (Test-FlhIsWindows) { return (Get-FlhWindowsPlatform) }
    return (Get-FlhPosixPlatform)
}

# ---------------------------------------------------------------- options

function Resolve-FlhDir {
    param([string]$Path, [string]$What, [switch]$MustExist, [switch]$File)
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "$What is not set" }
    if ($Path.IndexOf('"') -ge 0) { throw "$What must not contain a double quote: $Path" }
    if ($Path -match '[\x00-\x1f]') { throw "$What contains a control character" }
    if (-not [System.IO.Path]::IsPathRooted($Path)) { throw "$What must be an absolute path: $Path" }
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    while ($full.Length -gt $root.Length -and ($full.EndsWith('\') -or $full.EndsWith('/'))) { $full = $full.Substring(0, $full.Length - 1) }
    if ($MustExist) {
        $type = 'Container'
        if ($File) { $type = 'Leaf' }
        if (-not (Test-Path -LiteralPath $full -PathType $type)) { throw "$What does not exist: $full" }
    }
    return $full
}

function Resolve-FlhOptions {
    # $Bound: hashtable of the entry script's parameters. Throws on invalid values.
    param([hashtable]$Bound, [switch]$ForLaunch)
    $o = @{}
    $home_ = $env:USERPROFILE
    if (-not $home_) { $home_ = $env:HOME }
    $o.Port = 8765
    if ($Bound.ContainsKey('Port')) { $o.Port = [int]$Bound.Port }
    if ($o.Port -lt 1024 -or $o.Port -gt 65535) { throw "-Port must be 1024..65535" }
    $o.ServePort = 8765
    if ($Bound.ContainsKey('ServePort')) { $o.ServePort = [int]$Bound.ServePort }
    if ($o.ServePort -lt 1 -or $o.ServePort -gt 65535) { throw "-ServePort must be 1..65535" }
    $o.ReadyTimeoutSec = 300
    if ($Bound.ContainsKey('ReadyTimeoutSec')) { $o.ReadyTimeoutSec = [int]$Bound.ReadyTimeoutSec }
    if ($o.ReadyTimeoutSec -lt 1 -or $o.ReadyTimeoutSec -gt 3600) { throw "-ReadyTimeoutSec must be 1..3600" }
    $o.GracefulTimeoutSec = 30
    if ($Bound.ContainsKey('GracefulTimeoutSec')) { $o.GracefulTimeoutSec = [int]$Bound.GracefulTimeoutSec }
    if ($o.GracefulTimeoutSec -lt 1 -or $o.GracefulTimeoutSec -gt 300) { throw "-GracefulTimeoutSec must be 1..300" }
    $o.KeepRuns = 10
    if ($Bound.ContainsKey('KeepRuns')) { $o.KeepRuns = [int]$Bound.KeepRuns }
    if ($o.KeepRuns -lt 1 -or $o.KeepRuns -gt 100) { throw "-KeepRuns must be 1..100" }
    $o.Tail = 80
    if ($Bound.ContainsKey('Tail')) { $o.Tail = [int]$Bound.Tail }
    if ($o.Tail -lt 1 -or $o.Tail -gt 5000) { throw "-Tail must be 1..5000" }
    $o.ExpectedDeploymentId = $script:DefaultDeploymentId
    if ($Bound.ContainsKey('ExpectedDeploymentId') -and $Bound.ExpectedDeploymentId) { $o.ExpectedDeploymentId = [string]$Bound.ExpectedDeploymentId }

    $state = $null
    if ($Bound.ContainsKey('StateDir') -and $Bound.StateDir) { $state = [string]$Bound.StateDir }
    elseif ($env:LOCALAPPDATA) { $state = Join-Path $env:LOCALAPPDATA 'FLH\e5-runtime' }
    else { throw "-StateDir is required when LOCALAPPDATA is not set" }
    $o.StateDir = Resolve-FlhDir -Path $state -What '-StateDir'
    $o.RunsDir = Join-Path $o.StateDir 'runs'
    $o.CurrentPath = Join-Path $o.StateDir 'current.json'
    $o.LockPath = Join-Path $o.StateDir 'ops.lock'
    $o.ServeDir = Join-Path $o.StateDir 'serve'
    $o.RunnerPath = Join-Path $script:ModuleDir 'runner.py'

    $runtime = $null
    if ($Bound.ContainsKey('RuntimeDir') -and $Bound.RuntimeDir) { $runtime = [string]$Bound.RuntimeDir }
    elseif ($home_) { $runtime = Join-Path $home_ (Join-Path 'projects' 'flh-embedding-runtime') }
    $o.RuntimeDir = $runtime
    $o.E5Dir = $null
    if ($Bound.ContainsKey('E5Dir') -and $Bound.E5Dir) { $o.E5Dir = [string]$Bound.E5Dir }
    elseif ($runtime) {
        $nested = Join-Path $runtime (Join-Path 'tools' (Join-Path 'embedding' 'e5'))
        if (Test-Path -LiteralPath (Join-Path $nested 'flh_e5') -PathType Container) { $o.E5Dir = $nested } else { $o.E5Dir = $runtime }
    }
    $model = $null
    if ($Bound.ContainsKey('ModelDir') -and $Bound.ModelDir) { $model = [string]$Bound.ModelDir }
    elseif ($home_) { $model = Join-Path $home_ (Join-Path 'models' 'multilingual-e5-base') }
    $o.ModelDir = $model
    $o.CondaEnvName = 'flh-embedding'
    if ($Bound.ContainsKey('CondaEnvName') -and $Bound.CondaEnvName) { $o.CondaEnvName = [string]$Bound.CondaEnvName }
    $o.CondaPrefix = $null
    if ($Bound.ContainsKey('CondaPrefix') -and $Bound.CondaPrefix) { $o.CondaPrefix = [string]$Bound.CondaPrefix }
    $o.PythonExe = $null
    if ($Bound.ContainsKey('PythonExe') -and $Bound.PythonExe) { $o.PythonExe = [string]$Bound.PythonExe }

    if ($ForLaunch) {
        $o.E5Dir = Resolve-FlhDir -Path $o.E5Dir -What '-E5Dir (from -RuntimeDir)' -MustExist
        if (-not (Test-Path -LiteralPath (Join-Path $o.E5Dir (Join-Path 'flh_e5' '__main__.py')) -PathType Leaf)) {
            throw "no flh_e5 package in $($o.E5Dir) (expected flh_e5\__main__.py)"
        }
        $o.ModelDir = Resolve-FlhDir -Path $o.ModelDir -What '-ModelDir' -MustExist
        $missing = @()
        foreach ($f in $script:ModelFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $o.ModelDir $f) -PathType Leaf)) { $missing += $f }
        }
        if ($missing.Count -gt 0) { throw ("model directory {0} is missing: {1}" -f $o.ModelDir, ($missing -join ', ')) }
        if (-not $o.CondaPrefix) { $o.CondaPrefix = Find-FlhCondaPrefix -EnvName $o.CondaEnvName -HomeDir $home_ }
        $o.CondaPrefix = Resolve-FlhDir -Path $o.CondaPrefix -What '-CondaPrefix' -MustExist
        if (-not $o.PythonExe) { $o.PythonExe = Join-Path $o.CondaPrefix 'python.exe' }
        $o.PythonExe = Resolve-FlhDir -Path $o.PythonExe -What '-PythonExe' -MustExist -File
        $o.RunnerPath = Resolve-FlhDir -Path $o.RunnerPath -What 'runner.py' -MustExist -File
    }
    return $o
}

function Find-FlhCondaPrefix {
    param([string]$EnvName, [string]$HomeDir)
    $bases = @()
    if ($HomeDir) { foreach ($n in @('miniconda3', 'anaconda3', 'miniforge3', 'mambaforge')) { $bases += (Join-Path $HomeDir $n) } }
    if ($env:LOCALAPPDATA) { foreach ($n in @('miniconda3', 'anaconda3', 'miniforge3')) { $bases += (Join-Path $env:LOCALAPPDATA $n) } }
    if ($env:ProgramData) { foreach ($n in @('miniconda3', 'anaconda3', 'miniforge3')) { $bases += (Join-Path $env:ProgramData $n) } }
    $found = @()
    foreach ($b in $bases) {
        $c = Join-Path $b (Join-Path 'envs' $EnvName)
        if (Test-Path -LiteralPath (Join-Path $c 'python.exe') -PathType Leaf) { $found += $c }
    }
    if ($HomeDir) {
        $c = Join-Path $HomeDir (Join-Path '.conda' (Join-Path 'envs' $EnvName))
        if (Test-Path -LiteralPath (Join-Path $c 'python.exe') -PathType Leaf) { $found += $c }
    }
    $found = @($found | Sort-Object -Unique)
    if ($found.Count -eq 0) { throw "Conda environment '$EnvName' not found in the usual locations; pass -CondaPrefix <env dir>" }
    if ($found.Count -gt 1) { throw ("Conda environment '{0}' found in several places ({1}); pass -CondaPrefix" -f $EnvName, ($found -join '; ')) }
    return $found[0]
}

function Get-FlhCondaEnvironment {
    # What `conda activate` sets that matters to a Python process (activate.d
    # scripts are not run; `check` lists any that exist).
    param([string]$Prefix, [string]$EnvName)
    $dirs = @()
    foreach ($rel in @('', 'Library\mingw-w64\bin', 'Library\usr\bin', 'Library\bin', 'Scripts', 'bin')) {
        $d = $Prefix
        if ($rel) { $d = Join-Path $Prefix $rel }
        if (Test-Path -LiteralPath $d -PathType Container) { $dirs += $d }
    }
    $set = [ordered]@{
        CONDA_PREFIX = $Prefix; CONDA_DEFAULT_ENV = $EnvName
        HF_HUB_OFFLINE = '1'; TRANSFORMERS_OFFLINE = '1'
        PYTHONUNBUFFERED = '1'; PYTHONIOENCODING = 'utf-8'
    }
    return @{ Set = $set; PathPrepend = $dirs }
}

# ---------------------------------------------------------------- lock

function Enter-FlhLock {
    param([string]$Path, [int]$TimeoutSec = 15)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    while ($true) {
        try {
            return [System.IO.File]::Open($Path, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch [System.IO.IOException] {
            if ([DateTime]::UtcNow -gt $deadline) { throw "another flh-e5 start/stop holds $Path" }
            Start-Sleep -Milliseconds 250
        }
    }
}

# ---------------------------------------------------------------- run state

function Test-FlhCommandContains {
    param([string]$CommandLine, [string]$Needle)
    if (-not $CommandLine -or -not $Needle) { return $false }
    return ($CommandLine.IndexOf($Needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
}

function Get-FlhRunState {
    # Inspect the recorded run. Returns a table with Record, RunnerAlive,
    # ChildAlive (both only when proven owned), pids, Exit and Notes.
    param([hashtable]$Options, [hashtable]$Platform)
    $s = @{ Record = $null; RunnerAlive = $false; ChildAlive = $false; RunnerPid = $null; ChildPid = $null; Exit = $null; Notes = @(); RunDir = $null }
    $rec = Read-FlhJson -Path $Options.CurrentPath
    if ($null -eq $rec) { return $s }
    $s.Record = $rec
    $s.RunDir = [string](Get-FlhProp $rec 'run_dir')
    $s.Exit = Read-FlhJson -Path (Join-Path $s.RunDir 'exit.json')
    $runner = Get-FlhProp $rec 'runner'
    $specPath = [string](Get-FlhProp $rec 'spec_path')
    if ($null -ne $runner) {
        $s.RunnerPid = [int](Get-FlhProp $runner 'pid')
        $p = & $Platform.GetProcess $s.RunnerPid
        if ($null -ne $p) {
            if ($p.Created -eq [string](Get-FlhProp $runner 'created') -and (Test-FlhCommandContains $p.CommandLine $specPath)) {
                $s.RunnerAlive = $true
            } else {
                $s.Notes += ("PID {0} is now an unrelated process; not touched" -f $s.RunnerPid)
            }
        }
    }
    $child = Get-FlhProp $rec 'child'
    if ($null -eq $child -and $s.RunnerAlive) {
        # start was interrupted before it recorded the child: adopt it only via the owned supervisor
        $rj = Read-FlhJson -Path (Join-Path $s.RunDir 'runner.json')
        $cp = Get-FlhProp $rj 'child_pid'
        if ($null -ne $cp) {
            $p = & $Platform.GetProcess ([int]$cp)
            if ($null -ne $p -and $p.ParentId -eq $s.RunnerPid) {
                $child = [pscustomobject]@{ pid = [int]$cp; created = $p.Created }
                $rec | Add-Member -NotePropertyName child -NotePropertyValue $child -Force
                Write-FlhJson -Path $Options.CurrentPath -Object $rec
            }
        }
    }
    if ($null -ne $child) {
        $s.ChildPid = [int](Get-FlhProp $child 'pid')
        $p = & $Platform.GetProcess $s.ChildPid
        if ($null -ne $p) {
            $port = [string](Get-FlhProp $rec 'port')
            $ok = ($p.Created -eq [string](Get-FlhProp $child 'created')) -and ($p.CommandLine -match '-m\s+flh_e5\s+serve') -and
                  (Test-FlhCommandContains $p.CommandLine ("--port " + $port))
            if ($ok -and $s.RunnerAlive -and $p.ParentId -ne $s.RunnerPid) { $ok = $false }
            if ($ok) { $s.ChildAlive = $true } else { $s.Notes += ("PID {0} is now an unrelated process; not touched" -f $s.ChildPid) }
        }
    }
    return $s
}

function Complete-FlhRecord {
    # Move current.json into its run directory as final.json.
    param([hashtable]$Options, [hashtable]$State, [string]$Outcome)
    $rec = $State.Record
    if ($null -eq $rec) { return }
    $rec | Add-Member -NotePropertyName outcome -NotePropertyValue $Outcome -Force
    $rec | Add-Member -NotePropertyName finished_utc -NotePropertyValue (Get-FlhUtcNow) -Force
    if ($State.RunDir -and (Test-Path -LiteralPath $State.RunDir -PathType Container)) {
        Write-FlhJson -Path (Join-Path $State.RunDir 'final.json') -Object $rec
    }
    Remove-Item -LiteralPath $Options.CurrentPath -Force -ErrorAction SilentlyContinue
}

function Get-FlhTail {
    param([string]$Path, [int]$Lines)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @() }
    return @(Get-Content -LiteralPath $Path -Tail $Lines -Encoding UTF8)
}

function Remove-FlhOldRuns {
    param([hashtable]$Options, [string]$KeepRunId)
    if (-not (Test-Path -LiteralPath $Options.RunsDir -PathType Container)) { return 0 }
    $runs = @(Get-ChildItem -LiteralPath $Options.RunsDir -Directory | Where-Object { $_.Name -match $script:RunIdPattern } | Sort-Object Name -Descending)
    $removed = 0
    $kept = 0
    foreach ($r in $runs) {
        if ($r.Name -eq $KeepRunId) { continue }
        if ($kept -lt ($Options.KeepRuns - 1)) { $kept++; continue }
        Remove-Item -LiteralPath $r.FullName -Recurse -Force
        $removed++
    }
    return $removed
}

# ---------------------------------------------------------------- readiness

function Get-FlhReadiness {
    # Model state as the service reports it; Ready only with the expected identity.
    param([hashtable]$Options, [hashtable]$Platform, [string]$Expected)
    $base = "http://127.0.0.1:{0}" -f $Options.Port
    $r = & $Platform.HttpGet ($base + '/readyz') 3
    $res = @{ Answer = $false; Ready = $false; State = 'no answer'; DeploymentId = $null; IdentityMatch = $false; Error = $r.Error }
    if ($r.Status -eq 0) { return $res }
    $res.Answer = $true
    $body = $null
    try { $body = $r.Body | ConvertFrom-Json } catch { $body = $null }
    $st = Get-FlhProp $body 'state'
    if ($st) { $res.State = [string]$st } else { $res.State = "HTTP $($r.Status)" }
    if ($r.Status -ne 200) { return $res }
    $m = & $Platform.HttpGet ($base + '/manifest') 5
    $man = $null
    try { $man = $m.Body | ConvertFrom-Json } catch { $man = $null }
    $res.DeploymentId = [string](Get-FlhProp $man 'deployment_id')
    $res.IdentityMatch = ($m.Status -eq 200 -and $res.DeploymentId -ceq $Expected)
    $res.Ready = $res.IdentityMatch
    if ($res.IdentityMatch) { $res.State = 'ready' } else { $res.State = 'identity mismatch' }
    return $res
}

# ---------------------------------------------------------------- actions

function Invoke-FlhStart {
    param([hashtable]$Options, [hashtable]$Platform)
    $o = $Options
    $null = New-Item -ItemType Directory -Force -Path $o.RunsDir
    $lock = Enter-FlhLock -Path $o.LockPath
    $expected = $o.ExpectedDeploymentId
    try {
        $s = Get-FlhRunState -Options $o -Platform $Platform
        foreach ($n in $s.Notes) { Write-FlhLine "note: $n" }
        if ($s.ChildAlive) {
            Write-FlhLine ("already running: run {0}, service PID {1}; not launching another" -f (Get-FlhProp $s.Record 'run_id'), $s.ChildPid)
            $expected = [string](Get-FlhProp $s.Record 'expected_deployment_id')
            $launched = $false
        } else {
            if ($null -ne $s.Record) {
                if ($s.RunnerAlive) {
                    Write-FlhLine ("the recorded supervisor PID {0} is alive without a service; stopping it" -f $s.RunnerPid)
                    & $Platform.KillProcess $s.RunnerPid
                }
                Write-FlhLine ("previous run {0} is not running; archived its record" -f (Get-FlhProp $s.Record 'run_id'))
                Complete-FlhRecord -Options $o -State $s -Outcome 'stale'
            }
            $listeners = & $Platform.GetListenerPids $o.Port
            if ($listeners.Count -gt 0) {
                foreach ($lp in $listeners) {
                    $p = & $Platform.GetProcess $lp
                    $desc = '(process details unavailable)'
                    if ($null -ne $p) { $desc = "$($p.Name) $($p.CommandLine)" }
                    Write-FlhLine ("refused: port {0} is already in use by PID {1} {2}" -f $o.Port, $lp, $desc)
                }
                Write-FlhLine "nothing was launched and nothing was stopped"
                return 2
            }
            $others = & $Platform.ListEncoderProcesses
            if ($others.Count -gt 0) {
                foreach ($e in $others) { Write-FlhLine ("refused: another flh_e5 service is running: PID {0}: {1}" -f $e.Id, $e.CommandLine) }
                Write-FlhLine "nothing was launched; stop that service from where it was started"
                return 2
            }
            $runId = ([DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'")) + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
            $removed = Remove-FlhOldRuns -Options $o -KeepRunId $runId
            if ($removed -gt 0) { Write-FlhLine ("retention: removed {0} old run director{1}" -f $removed, $(if ($removed -eq 1) { 'y' } else { 'ies' })) }
            $runDir = Join-Path $o.RunsDir $runId
            $null = New-Item -ItemType Directory -Path $runDir
            $specPath = Join-Path $runDir 'launch.json'
            $envs = Get-FlhCondaEnvironment -Prefix $o.CondaPrefix -EnvName $o.CondaEnvName
            $serveArgs = @('-B', '-m', 'flh_e5', 'serve', '--model-dir', $o.ModelDir, '--host', '127.0.0.1', '--port', [string]$o.Port) + $script:ServeArgsFixed
            $spec = [ordered]@{
                schema = 'flh065_e5_launch_v1'; run_id = $runId; run_dir = $runDir
                python = $o.PythonExe; args = $serveArgs; cwd = $o.E5Dir
                env_set = $envs.Set; env_path_prepend = $envs.PathPrepend
                stdout_log = (Join-Path $runDir 'stdout.log'); stderr_log = (Join-Path $runDir 'stderr.log')
                stop_request = (Join-Path $runDir 'stop-request.json'); graceful_timeout_s = $o.GracefulTimeoutSec
                expected_deployment_id = $expected
            }
            Write-FlhJson -Path $specPath -Object $spec
            $runnerArgs = Join-FlhCommandLine @('-B', '-I', $o.RunnerPath, '--spec', $specPath)
            Write-FlhLine ("run {0}: launching the supervisor ({1})" -f $runId, $Platform.Name)
            Write-FlhLine ("  python   {0}" -f $o.PythonExe)
            Write-FlhLine ("  e5 dir   {0}" -f $o.E5Dir)
            Write-FlhLine ("  model    {0}" -f $o.ModelDir)
            Write-FlhLine ("  listen   127.0.0.1:{0}, float16, microbatch 8, singleton_v1" -f $o.Port)
            $runnerPid = & $Platform.StartDetached $o.PythonExe $runnerArgs $runDir
            $rp = & $Platform.GetProcess $runnerPid
            $created = $null
            if ($null -ne $rp) { $created = $rp.Created }
            $rec = [ordered]@{
                schema = 'flh065_e5_current_v1'; run_id = $runId; run_dir = $runDir; spec_path = $specPath; port = $o.Port
                expected_deployment_id = $expected; model_dir = $o.ModelDir; e5_dir = $o.E5Dir; python = $o.PythonExe
                launched_utc = (Get-FlhUtcNow); runner = [ordered]@{ pid = $runnerPid; created = $created }; child = $null
            }
            Write-FlhJson -Path $o.CurrentPath -Object $rec
            # the supervisor reports the service PID in runner.json
            $deadline = [DateTime]::UtcNow.AddSeconds(30)
            $childPid = $null
            while ([DateTime]::UtcNow -lt $deadline) {
                $rj = Read-FlhJson -Path (Join-Path $runDir 'runner.json')
                $cp = Get-FlhProp $rj 'child_pid'
                if ($null -ne $cp) { $childPid = [int]$cp; break }
                if ($null -eq (& $Platform.GetProcess $runnerPid)) { break }
                Start-Sleep -Milliseconds 200
            }
            if ($null -eq $childPid) {
                Write-FlhLine "startup failed: the supervisor did not start the service"
                foreach ($l in (Get-FlhTail -Path (Join-Path $runDir 'runner.log') -Lines 20)) { Write-FlhLine "  runner.log: $l" }
                $st = Get-FlhRunState -Options $o -Platform $Platform
                if ($st.RunnerAlive) { & $Platform.KillProcess $st.RunnerPid }
                Complete-FlhRecord -Options $o -State $st -Outcome 'launch_failed'
                return 1
            }
            $cpInfo = & $Platform.GetProcess $childPid
            $cCreated = $null
            if ($null -ne $cpInfo) { $cCreated = $cpInfo.Created }
            $rec.child = [ordered]@{ pid = $childPid; created = $cCreated }
            Write-FlhJson -Path $o.CurrentPath -Object $rec
            Write-FlhLine ("  supervisor PID {0}, service PID {1}" -f $runnerPid, $childPid)
            $launched = $true
        }
    } finally {
        $lock.Close()
    }
    return (Wait-FlhReady -Options $o -Platform $Platform -Expected $expected -Launched $launched)
}

function Wait-FlhReady {
    param([hashtable]$Options, [hashtable]$Platform, [string]$Expected, [bool]$Launched)
    $o = $Options
    $deadline = [DateTime]::UtcNow.AddSeconds($o.ReadyTimeoutSec)
    $last = ''
    $started = [DateTime]::UtcNow
    while ($true) {
        $s = Get-FlhRunState -Options $o -Platform $Platform
        if (-not $s.ChildAlive) {
            Start-Sleep -Milliseconds 500   # let the supervisor write exit.json
            $s = Get-FlhRunState -Options $o -Platform $Platform
            $code = Get-FlhProp $s.Exit 'child_exit_code'
            Write-FlhLine ("startup failed: the service exited (exit code {0}) before it was ready" -f $code)
            foreach ($l in (Get-FlhTail -Path (Join-Path $s.RunDir 'stderr.log') -Lines 25)) { Write-FlhLine "  stderr: $l" }
            Write-FlhLine ("  logs: {0}" -f $s.RunDir)
            if ($s.RunnerAlive) {
                $null = Stop-FlhOwnedRun -Options $o -Platform $Platform -State $s -Force
            } else {
                Complete-FlhRecord -Options $o -State $s -Outcome 'startup_failed'
            }
            return 1
        }
        $listeners = & $Platform.GetListenerPids $o.Port
        $foreign = @($listeners | Where-Object { $_ -ne $s.ChildPid })
        if ($foreign.Count -gt 0) {
            Write-FlhLine ("startup failed: port {0} is held by PID {1}, not by the service" -f $o.Port, ($foreign -join ', '))
            if ($Launched) { $null = Stop-FlhOwnedRun -Options $o -Platform $Platform -State $s }
            return 1
        }
        $r = Get-FlhReadiness -Options $o -Platform $Platform -Expected $Expected
        if ($r.State -ne $last) {
            $secs = [int]([DateTime]::UtcNow - $started).TotalSeconds
            Write-FlhLine ("  [{0,3}s] model state: {1}" -f $secs, $r.State)
            $last = $r.State
        }
        if ($r.Ready) {
            Write-FlhLine ("ready: deployment_id {0}" -f $r.DeploymentId)
            Write-FlhLine ("  service PID {0} on 127.0.0.1:{1}; logs {2}" -f $s.ChildPid, $o.Port, $s.RunDir)
            return 0
        }
        if ($r.State -eq 'identity mismatch') {
            Write-FlhLine ("startup failed: deployment_id {0}" -f $r.DeploymentId)
            Write-FlhLine ("  expected       {0}" -f $Expected)
            if ($Launched) {
                Write-FlhLine "  stopping the run this command launched"
                $null = Stop-FlhOwnedRun -Options $o -Platform $Platform -State $s
            } else {
                Write-FlhLine "  the service was already running; it was left as is"
            }
            return 1
        }
        if ([DateTime]::UtcNow -gt $deadline) {
            Write-FlhLine ("not ready after {0}s (state: {1}); the service is left running. Check: status, logs; or stop" -f $o.ReadyTimeoutSec, $r.State)
            return 4
        }
        Start-Sleep -Milliseconds 1000
    }
}

function Stop-FlhOwnedRun {
    # Stop the recorded run: stop request to the supervisor, bounded waits,
    # then terminate only proven-owned PIDs. Returns 0 or 1.
    param([hashtable]$Options, [hashtable]$Platform, [hashtable]$State, [switch]$Force)
    $o = $Options
    $s = $State
    $mode = 'graceful'
    if ($Force) { $mode = 'force' }
    $outcome = 'stopped'
    if ($s.RunnerAlive -and $s.ChildAlive) {
        $req = [ordered]@{ mode = $mode; graceful_timeout_s = $o.GracefulTimeoutSec; requested_utc = (Get-FlhUtcNow) }
        Write-FlhJson -Path (Join-Path $s.RunDir 'stop-request.json') -Object $req
        Write-FlhLine ("stop requested ({0}); waiting up to {1}s" -f $mode, ($o.GracefulTimeoutSec + 15))
        $deadline = [DateTime]::UtcNow.AddSeconds($o.GracefulTimeoutSec + 15)
        while ([DateTime]::UtcNow -lt $deadline) {
            $s = Get-FlhRunState -Options $o -Platform $Platform
            if (-not $s.ChildAlive -and -not $s.RunnerAlive) { break }
            Start-Sleep -Milliseconds 500
        }
    }
    $s = Get-FlhRunState -Options $o -Platform $Platform
    if ($s.ChildAlive) {
        Write-FlhLine ("terminating the service PID {0} (proven owned; the supervisor did not stop it)" -f $s.ChildPid)
        & $Platform.KillProcess $s.ChildPid
        $outcome = 'terminated_by_operator'
        Start-Sleep -Milliseconds 500
    }
    $s = Get-FlhRunState -Options $o -Platform $Platform
    if ($s.RunnerAlive) {
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        while ($s.RunnerAlive -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 500
            $s = Get-FlhRunState -Options $o -Platform $Platform
        }
        if ($s.RunnerAlive) {
            Write-FlhLine ("terminating the supervisor PID {0} (proven owned)" -f $s.RunnerPid)
            & $Platform.KillProcess $s.RunnerPid
            Start-Sleep -Milliseconds 300
            $s = Get-FlhRunState -Options $o -Platform $Platform
        }
    }
    if ($s.ChildAlive -or $s.RunnerAlive) {
        Write-FlhLine "stop failed: an owned process is still running"
        return 1
    }
    $exit = Get-FlhProp $s.Exit 'reason'
    $code = Get-FlhProp $s.Exit 'child_exit_code'
    if ($exit) { Write-FlhLine ("stopped: {0} (service exit code {1})" -f $exit, $code) } else { Write-FlhLine "stopped" }
    Complete-FlhRecord -Options $o -State $s -Outcome $outcome
    return 0
}

function Invoke-FlhStop {
    param([hashtable]$Options, [hashtable]$Platform, [switch]$Force)
    $o = $Options
    if (-not (Test-Path -LiteralPath $o.StateDir -PathType Container)) { Write-FlhLine "not running (no state directory)"; return 0 }
    $lock = Enter-FlhLock -Path $o.LockPath
    try {
        $s = Get-FlhRunState -Options $o -Platform $Platform
        foreach ($n in $s.Notes) { Write-FlhLine "note: $n" }
        $code = 0
        if ($null -eq $s.Record) {
            Write-FlhLine "not running (no recorded run)"
        } elseif (-not $s.ChildAlive -and -not $s.RunnerAlive) {
            Write-FlhLine ("not running; archived the record of run {0}" -f (Get-FlhProp $s.Record 'run_id'))
            Complete-FlhRecord -Options $o -State $s -Outcome 'stale'
        } else {
            $code = Stop-FlhOwnedRun -Options $o -Platform $Platform -State $s -Force:$Force
        }
        $listeners = & $Platform.GetListenerPids $o.Port
        if ($listeners.Count -gt 0) {
            Write-FlhLine ("note: port {0} is still in use by PID {1}; not started by this tool, not touched" -f $o.Port, ($listeners -join ', '))
        } elseif ($code -eq 0) {
            Write-FlhLine ("port {0} is free" -f $o.Port)
        }
        return $code
    } finally {
        $lock.Close()
    }
}

function Invoke-FlhStatus {
    param([hashtable]$Options, [hashtable]$Platform, [switch]$Json)
    $o = $Options
    $s = Get-FlhRunState -Options $o -Platform $Platform
    $listeners = & $Platform.GetListenerPids $o.Port
    $expected = $o.ExpectedDeploymentId
    if ($null -ne $s.Record) { $expected = [string](Get-FlhProp $s.Record 'expected_deployment_id') }
    $r = @{ Answer = $false; Ready = $false; State = 'not queried'; DeploymentId = $null; IdentityMatch = $false }
    if ($listeners.Count -gt 0) { $r = Get-FlhReadiness -Options $o -Platform $Platform -Expected $expected }
    $foreign = @($listeners | Where-Object { -not ($s.ChildAlive -and $_ -eq $s.ChildPid) })
    if ($s.ChildAlive) {
        if ($foreign.Count -gt 0) { $summary = 'port conflict'; $code = 1 }
        elseif ($r.Ready) { $summary = 'ready'; $code = 0 }
        elseif ($r.State -eq 'identity mismatch' -or $r.State -eq 'failed') { $summary = $r.State; $code = 1 }
        else { $summary = 'running, model not ready'; $code = 4 }
    } elseif ($foreign.Count -gt 0) {
        $summary = 'stopped (port used by another process)'; $code = 1
    } else {
        $summary = 'stopped'; $code = 3
    }
    $last = $null
    if ($null -ne $s.Record) { $last = Get-FlhProp $s.Record 'run_id' }
    $obj = [ordered]@{
        schema = 'flh065_e5_status_v1'; summary = $summary; exit_code = $code; port = $o.Port
        run_id = $last; run_dir = $s.RunDir
        supervisor = [ordered]@{ pid = $s.RunnerPid; running = $s.RunnerAlive }
        service = [ordered]@{ pid = $s.ChildPid; running = $s.ChildAlive }
        model = [ordered]@{ answered = $r.Answer; state = $r.State; deployment_id = $r.DeploymentId; expected_deployment_id = $expected; identity_match = $r.IdentityMatch }
        listeners = @($listeners); unrelated_listeners = @($foreign); last_exit = $s.Exit; notes = @($s.Notes)
    }
    if ($Json) {
        Write-Host ($obj | ConvertTo-Json -Depth 6)
        return $code
    }
    Write-FlhLine ("status: {0}" -f $summary)
    if ($null -ne $s.Record) {
        Write-FlhLine ("  run         {0}" -f $last)
        Write-FlhLine ("  supervisor  PID {0}: {1}" -f $s.RunnerPid, $(if ($s.RunnerAlive) { 'running' } else { 'not running' }))
        Write-FlhLine ("  service     PID {0}: {1}" -f $s.ChildPid, $(if ($s.ChildAlive) { 'running' } else { 'not running' }))
        if ($null -ne $s.Exit) { Write-FlhLine ("  last exit   {0} (code {1})" -f (Get-FlhProp $s.Exit 'reason'), (Get-FlhProp $s.Exit 'child_exit_code')) }
    } else {
        Write-FlhLine "  no recorded run"
    }
    Write-FlhLine ("  model       {0}" -f $r.State)
    if ($r.DeploymentId) { Write-FlhLine ("  identity    {0} ({1})" -f $r.DeploymentId, $(if ($r.IdentityMatch) { 'matches' } else { 'DOES NOT MATCH expected' })) }
    if ($foreign.Count -gt 0) { Write-FlhLine ("  port {0} is used by unrelated PID {1}" -f $o.Port, ($foreign -join ', ')) }
    foreach ($n in $s.Notes) { Write-FlhLine "  note: $n" }
    return $code
}

function Invoke-FlhLogs {
    param([hashtable]$Options, [string]$Run, [string]$Stream = 'stderr', [switch]$List)
    $o = $Options
    if (-not (Test-Path -LiteralPath $o.RunsDir -PathType Container)) { Write-FlhLine "no runs recorded in $($o.StateDir)"; return 0 }
    $runs = @(Get-ChildItem -LiteralPath $o.RunsDir -Directory | Where-Object { $_.Name -match $script:RunIdPattern } | Sort-Object Name -Descending)
    if ($List) {
        foreach ($r in $runs) {
            $ex = Read-FlhJson -Path (Join-Path $r.FullName 'exit.json')
            $what = 'running or unknown'
            if ($null -ne $ex) { $what = "{0} (code {1})" -f (Get-FlhProp $ex 'reason'), (Get-FlhProp $ex 'child_exit_code') }
            $bytes = 0
            foreach ($f in @(Get-ChildItem -LiteralPath $r.FullName -File)) { $bytes += $f.Length }
            Write-FlhLine ("{0}  {1,9} bytes  {2}" -f $r.Name, $bytes, $what)
        }
        return 0
    }
    $target = $null
    if ($Run -and $Run -ne 'latest') {
        if ($Run -notmatch $script:RunIdPattern) { Write-FlhLine "-Run must be a run ID (see logs -List) or 'latest'"; return 2 }
        $target = Join-Path $o.RunsDir $Run
        if (-not (Test-Path -LiteralPath $target -PathType Container)) { Write-FlhLine "no such run: $Run"; return 2 }
    } elseif ($runs.Count -gt 0) {
        $target = $runs[0].FullName
    } else {
        Write-FlhLine "no runs recorded"; return 0
    }
    $streams = @($Stream)
    if ($Stream -eq 'all') { $streams = @('runner', 'stdout', 'stderr') }
    Write-FlhLine ("run {0}" -f (Split-Path -Leaf $target))
    foreach ($st in $streams) {
        $path = Join-Path $target ($st + '.log')
        Write-FlhLine ("--- {0} (last {1} lines)" -f $path, $o.Tail)
        foreach ($l in (Get-FlhTail -Path $path -Lines $o.Tail)) { Write-FlhLine $l }
    }
    return 0
}

function Invoke-FlhCheck {
    # Read-only preflight. -VerifyFiles hashes the model files (flh_e5 verify-files);
    # -Cuda runs windows\check_env.py. Both run in this session, not detached.
    param([hashtable]$Bound, [hashtable]$Platform, [switch]$VerifyFiles, [switch]$Cuda)
    $ok = $true
    try {
        $o = Resolve-FlhOptions -Bound $Bound -ForLaunch
    } catch {
        Write-FlhLine ("check: FAILED: {0}" -f $_.Exception.Message)
        return 2
    }
    Write-FlhLine ("powershell  {0} {1}" -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition)
    Write-FlhLine ("platform    {0}" -f $Platform.Name)
    Write-FlhLine ("e5 dir      {0}" -f $o.E5Dir)
    Write-FlhLine ("model dir   {0} (6 pinned file names present)" -f $o.ModelDir)
    Write-FlhLine ("conda env   {0} ({1})" -f $o.CondaPrefix, $o.CondaEnvName)
    Write-FlhLine ("python      {0}" -f $o.PythonExe)
    $ver = (& $o.PythonExe --version 2>&1 | Out-String).Trim()
    Write-FlhLine ("            {0}" -f $ver)
    $act = Join-Path $o.CondaPrefix (Join-Path 'etc' (Join-Path 'conda' 'activate.d'))
    if (Test-Path -LiteralPath $act -PathType Container) {
        $scripts = @(Get-ChildItem -LiteralPath $act -File | ForEach-Object { $_.Name })
        if ($scripts.Count -gt 0) { Write-FlhLine ("warning: activate.d scripts are not run by this launcher: {0}" -f ($scripts -join ', ')) }
    }
    Write-FlhLine ("state dir   {0}" -f $o.StateDir)
    Write-FlhLine ("expected    {0}" -f $o.ExpectedDeploymentId)
    $listeners = & $Platform.GetListenerPids $o.Port
    if ($listeners.Count -gt 0) { Write-FlhLine ("port {0}    in use by PID {1}" -f $o.Port, ($listeners -join ', ')) } else { Write-FlhLine ("port {0}    free" -f $o.Port) }
    $others = & $Platform.ListEncoderProcesses
    foreach ($e in $others) { Write-FlhLine ("encoder     PID {0}: {1}" -f $e.Id, $e.CommandLine) }
    $ts = & $Platform.Tailscale @('version')
    if ($ts.ExitCode -eq 0) { Write-FlhLine ("tailscale   {0}" -f (($ts.Output -split "`n")[0]).Trim()) } else { Write-FlhLine "tailscale   not available" }
    $envs = Get-FlhCondaEnvironment -Prefix $o.CondaPrefix -EnvName $o.CondaEnvName
    if ($VerifyFiles -or $Cuda) {
        $savedPath = $env:PATH
        $saved = @{}
        foreach ($k in $envs.Set.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $envs.Set[$k]) }
        $env:PATH = (($envs.PathPrepend + @($savedPath)) -join [System.IO.Path]::PathSeparator)
        Push-Location -LiteralPath $o.E5Dir
        try {
            if ($VerifyFiles) {
                Write-FlhLine "verify-files (hashing about 1.1 GB):"
                & $o.PythonExe -B -m flh_e5 verify-files --model-dir $o.ModelDir 2>&1 | ForEach-Object { Write-FlhLine ("  " + $_) }
                if ($LASTEXITCODE -ne 0) { $ok = $false; Write-FlhLine "verify-files FAILED" }
            }
            if ($Cuda) {
                $checkPy = Join-Path $o.E5Dir (Join-Path 'windows' 'check_env.py')
                Write-FlhLine "check_env.py:"
                & $o.PythonExe -B $checkPy 2>&1 | ForEach-Object { Write-FlhLine ("  " + $_) }
                if ($LASTEXITCODE -ne 0) { $ok = $false; Write-FlhLine "CUDA check FAILED" }
            }
        } finally {
            Pop-Location
            $env:PATH = $savedPath
            foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
        }
    }
    if ($ok) { Write-FlhLine "check: ok"; return 0 }
    return 1
}

# ---------------------------------------------------------------- Tailscale Serve

function Get-FlhServeForwards {
    # Flatten `tailscale serve status --json` (including Foreground sessions)
    # into forwards: @{ Scope; Host; Port; Path; Kind; Target }.
    param($Config, [string]$Scope = 'background')
    $out = @()
    if ($null -eq $Config) { return , $out }
    $tcp = Get-FlhProp $Config 'TCP'
    if ($null -ne $tcp) {
        foreach ($prop in $tcp.PSObject.Properties) {
            $fwd = Get-FlhProp $prop.Value 'TCPForward'
            if ($fwd) { $out += @{ Scope = $Scope; Host = ''; Port = [string]$prop.Name; Path = ''; Kind = 'tcp'; Target = [string]$fwd } }
            elseif (Get-FlhProp $prop.Value 'HTTPS') { $out += @{ Scope = $Scope; Host = ''; Port = [string]$prop.Name; Path = ''; Kind = 'https-listener'; Target = '' } }
            elseif (Get-FlhProp $prop.Value 'HTTP') { $out += @{ Scope = $Scope; Host = ''; Port = [string]$prop.Name; Path = ''; Kind = 'http-listener'; Target = '' } }
        }
    }
    $web = Get-FlhProp $Config 'Web'
    if ($null -ne $web) {
        foreach ($hp in $web.PSObject.Properties) {
            $hostPort = [string]$hp.Name
            $port = ''
            $h = $hostPort
            $i = $hostPort.LastIndexOf(':')
            if ($i -ge 0) { $port = $hostPort.Substring($i + 1); $h = $hostPort.Substring(0, $i) }
            $handlers = Get-FlhProp $hp.Value 'Handlers'
            if ($null -eq $handlers) { continue }
            foreach ($pp in $handlers.PSObject.Properties) {
                $proxy = Get-FlhProp $pp.Value 'Proxy'
                $kind = 'proxy'
                $target = [string]$proxy
                if (-not $proxy) {
                    $kind = 'other'
                    if (Get-FlhProp $pp.Value 'Path') { $kind = 'path'; $target = [string](Get-FlhProp $pp.Value 'Path') }
                    elseif (Get-FlhProp $pp.Value 'Text') { $kind = 'text' }
                }
                $out += @{ Scope = $Scope; Host = $h; Port = $port; Path = [string]$pp.Name; Kind = $kind; Target = $target }
            }
        }
    }
    $fg = Get-FlhProp $Config 'Foreground'
    if ($null -ne $fg) {
        foreach ($sp in $fg.PSObject.Properties) { $out += (Get-FlhServeForwards -Config $sp.Value -Scope ('foreground session ' + $sp.Name)) }
    }
    return , $out
}

function Test-FlhServeTarget {
    param([string]$Target, [int]$Port)
    $t = $Target.Trim().TrimEnd('/')
    foreach ($ok in @("http://127.0.0.1:$Port", "http://localhost:$Port", "127.0.0.1:$Port", "localhost:$Port", "$Port")) {
        if ($t -ieq $ok) { return $true }
    }
    return $false
}

function Get-FlhServeConfig {
    param([hashtable]$Platform)
    $r = & $Platform.Tailscale @('serve', 'status', '--json')
    if ($r.ExitCode -ne 0) { return @{ Ok = $false; Error = ($r.Output.Trim()); Raw = $r.Output; Config = $null } }
    $text = $r.Output.Trim()
    $cfg = $null
    if ($text -and $text -ne '{}' -and $text -ne 'null') {
        try { $cfg = $text | ConvertFrom-Json } catch { return @{ Ok = $false; Error = "unparseable serve status JSON"; Raw = $text; Config = $null } }
    }
    return @{ Ok = $true; Error = $null; Raw = $text; Config = $cfg }
}

function Get-FlhFunnelOn {
    param($Config)
    $af = Get-FlhProp $Config 'AllowFunnel'
    if ($null -eq $af) { return $false }
    foreach ($p in $af.PSObject.Properties) { if ($p.Value) { return $true } }
    return $false
}

function Invoke-FlhServeStatus {
    param([hashtable]$Options, [hashtable]$Platform)
    $c = Get-FlhServeConfig -Platform $Platform
    if (-not $c.Ok) { Write-FlhLine ("serve-status: tailscale failed: {0}" -f $c.Error); return 1 }
    $fw = Get-FlhServeForwards -Config $c.Config
    if ($fw.Count -eq 0) { Write-FlhLine "no Tailscale Serve configuration" }
    $match = $false
    foreach ($f in $fw) {
        $mark = ''
        if ($f.Target -and (Test-FlhServeTarget -Target $f.Target -Port $Options.Port)) { $mark = '  <- this service'; $match = $true }
        Write-FlhLine ("{0}: port {1} {2} {3} -> {4}{5}" -f $f.Scope, $f.Port, $f.Kind, $f.Path, $f.Target, $mark)
    }
    if (Get-FlhFunnelOn -Config $c.Config) { Write-FlhLine "WARNING: Funnel (public internet) is enabled for some host; this service must never be funnelled" }
    if ($match) { Write-FlhLine ("a forward to 127.0.0.1:{0} exists" -f $Options.Port) } else { Write-FlhLine ("no forward to 127.0.0.1:{0}" -f $Options.Port) }
    return 0
}

function Invoke-FlhServeEnable {
    param([hashtable]$Options, [hashtable]$Platform)
    $o = $Options
    $c = Get-FlhServeConfig -Platform $Platform
    if (-not $c.Ok) { Write-FlhLine ("serve-enable: tailscale failed: {0}" -f $c.Error); return 1 }
    if (Get-FlhFunnelOn -Config $c.Config) { Write-FlhLine "refused: Funnel is enabled in the Serve configuration; resolve that first"; return 2 }
    $fw = Get-FlhServeForwards -Config $c.Config
    foreach ($f in $fw) {
        if ($f.Target -and (Test-FlhServeTarget -Target $f.Target -Port $o.Port)) {
            Write-FlhLine ("reusing the existing forward ({0}: port {1} -> {2}); no change made" -f $f.Scope, $f.Port, $f.Target)
            return 0
        }
    }
    foreach ($f in $fw) {
        if ($f.Port -eq [string]$o.ServePort) {
            Write-FlhLine ("refused: Serve port {0} already carries {1} {2} -> {3}; not changed" -f $o.ServePort, $f.Kind, $f.Path, $f.Target)
            return 2
        }
    }
    $null = New-Item -ItemType Directory -Force -Path $o.ServeDir
    $target = "http://127.0.0.1:{0}" -f $o.Port
    $cmd = @('serve', '--bg', ("--http={0}" -f $o.ServePort), $target)
    Write-FlhLine ("changing Tailscale Serve: tailscale {0}" -f ($cmd -join ' '))
    Write-FlhLine "  this is persistent: it survives reboots until serve-disable removes it"
    $r = & $Platform.Tailscale $cmd
    $after = Get-FlhServeConfig -Platform $Platform
    $rec = [ordered]@{ schema = 'flh065_serve_change_v1'; action = 'enable'; command = ('tailscale ' + ($cmd -join ' ')); exit_code = $r.ExitCode
        serve_port = $o.ServePort; target = $target; before = $c.Raw; after = $after.Raw; utc = (Get-FlhUtcNow) }
    Write-FlhJson -Path (Join-Path $o.ServeDir ('change-' + [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'") + '.json')) -Object $rec
    if ($r.ExitCode -ne 0) { Write-FlhLine ("serve-enable FAILED: {0}" -f $r.Output.Trim()); return 1 }
    $ok = $false
    foreach ($f in (Get-FlhServeForwards -Config $after.Config)) {
        if ($f.Port -eq [string]$o.ServePort -and $f.Target -and (Test-FlhServeTarget -Target $f.Target -Port $o.Port)) { $ok = $true }
    }
    if (-not $ok) { Write-FlhLine "serve-enable: the forward is not visible in serve status afterwards"; return 1 }
    Write-FlhJson -Path (Join-Path $o.ServeDir 'owned-forward.json') -Object ([ordered]@{ serve_port = $o.ServePort; target = $target; enabled_utc = (Get-FlhUtcNow) })
    Write-FlhLine ("enabled: tailnet port {0} -> {1}" -f $o.ServePort, $target)
    return 0
}

function Invoke-FlhServeDisable {
    param([hashtable]$Options, [hashtable]$Platform)
    $o = $Options
    $ownedPath = Join-Path $o.ServeDir 'owned-forward.json'
    $owned = Read-FlhJson -Path $ownedPath
    if ($null -eq $owned) { Write-FlhLine "nothing to disable: this tool has not recorded adding a forward (existing forwards are never removed)"; return 0 }
    $c = Get-FlhServeConfig -Platform $Platform
    if (-not $c.Ok) { Write-FlhLine ("serve-disable: tailscale failed: {0}" -f $c.Error); return 1 }
    $sp = [string](Get-FlhProp $owned 'serve_port')
    $atPort = @((Get-FlhServeForwards -Config $c.Config) | Where-Object { $_.Port -eq $sp -and $_.Scope -eq 'background' -and $_.Kind -ne 'http-listener' -and $_.Kind -ne 'https-listener' })
    if ($atPort.Count -eq 0) {
        Write-FlhLine ("the recorded forward on port {0} is already gone; record cleared" -f $sp)
        Remove-Item -LiteralPath $ownedPath -Force
        return 0
    }
    if ($atPort.Count -ne 1 -or $atPort[0].Path -ne '/' -or -not (Test-FlhServeTarget -Target $atPort[0].Target -Port $o.Port)) {
        Write-FlhLine ("refused: port {0} no longer carries exactly the recorded forward; not changed" -f $sp)
        return 2
    }
    $cmd = @('serve', ("--http={0}" -f $sp), 'off')
    Write-FlhLine ("changing Tailscale Serve: tailscale {0}" -f ($cmd -join ' '))
    $r = & $Platform.Tailscale $cmd
    $after = Get-FlhServeConfig -Platform $Platform
    $null = New-Item -ItemType Directory -Force -Path $o.ServeDir
    $rec = [ordered]@{ schema = 'flh065_serve_change_v1'; action = 'disable'; command = ('tailscale ' + ($cmd -join ' ')); exit_code = $r.ExitCode
        serve_port = [int]$sp; before = $c.Raw; after = $after.Raw; utc = (Get-FlhUtcNow) }
    Write-FlhJson -Path (Join-Path $o.ServeDir ('change-' + [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'") + '.json')) -Object $rec
    if ($r.ExitCode -ne 0) { Write-FlhLine ("serve-disable FAILED: {0}" -f $r.Output.Trim()); return 1 }
    Remove-Item -LiteralPath $ownedPath -Force
    Write-FlhLine ("disabled: tailnet port {0}" -f $sp)
    return 0
}

# ---------------------------------------------------------------- dispatch

function Invoke-FlhAction {
    # Exit codes: see docs/WINDOWS_EMBEDDING_OPERATIONS.md.
    param([string]$Action, [hashtable]$Bound, [hashtable]$Platform)
    if ($null -eq $Platform) { $Platform = Get-FlhDefaultPlatform }
    $script:Quiet = ($Action -eq 'status' -and $Bound.ContainsKey('Json') -and [bool]$Bound.Json)
    if ($Action -eq 'check') { return (Invoke-FlhCheck -Bound $Bound -Platform $Platform -VerifyFiles:([bool]$Bound['VerifyFiles']) -Cuda:([bool]$Bound['Cuda'])) }
    try {
        $o = Resolve-FlhOptions -Bound $Bound -ForLaunch:($Action -eq 'start')
    } catch {
        Write-Host ("refused: {0}" -f $_.Exception.Message)
        return 2
    }
    switch ($Action) {
        'start' { return (Invoke-FlhStart -Options $o -Platform $Platform) }
        'status' { return (Invoke-FlhStatus -Options $o -Platform $Platform -Json:([bool]$Bound['Json'])) }
        'stop' { return (Invoke-FlhStop -Options $o -Platform $Platform -Force:([bool]$Bound['Force'])) }
        'logs' {
            $stream = 'stderr'
            if ($Bound.ContainsKey('Stream') -and $Bound.Stream) { $stream = [string]$Bound.Stream }
            return (Invoke-FlhLogs -Options $o -Run ([string]$Bound['Run']) -Stream $stream -List:([bool]$Bound['List']))
        }
        'serve-status' { return (Invoke-FlhServeStatus -Options $o -Platform $Platform) }
        'serve-enable' { return (Invoke-FlhServeEnable -Options $o -Platform $Platform) }
        'serve-disable' { return (Invoke-FlhServeDisable -Options $o -Platform $Platform) }
        default { Write-Host "unknown action: $Action"; return 2 }
    }
}

Export-ModuleMember -Function Invoke-FlhAction, ConvertTo-FlhArgument, Join-FlhCommandLine, Get-FlhServeForwards, Test-FlhServeTarget, Get-FlhWindowsPlatform, Get-FlhPosixPlatform, Resolve-FlhOptions
