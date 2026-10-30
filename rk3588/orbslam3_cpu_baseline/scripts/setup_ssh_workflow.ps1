param([string]$SshAlias = 'rk3588', [string]$RemoteRoot = '~/orbslam3_cpu_baseline')
$ErrorActionPreference = 'Stop'
$ExperimentRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ExperimentRoot '..\..\scripts\project_env.ps1')
if ($SshAlias -notmatch '^[A-Za-z0-9_.-]+$' -or $SshAlias.StartsWith('-')) { throw 'Invalid alias' }
if ($RemoteRoot -notmatch '^(~/|/)[A-Za-z0-9_./-]+$') { throw 'Invalid remote root' }
$sshOptions = @('-o','BatchMode=yes','-o','NumberOfPasswordPrompts=0','-o','ConnectTimeout=10')
$shellRoot = if ($RemoteRoot.StartsWith('~/')) { '${HOME}/' + $RemoteRoot.Substring(2) } else { $RemoteRoot }
& ssh @sshOptions $SshAlias ('test -d "' + $shellRoot + '" && python3 --version')
if ($LASTEXITCODE) { throw 'Existing SSH alias or board workspace is unavailable; no password retry performed' }
& scp @sshOptions (Join-Path $PSScriptRoot 'remote_job.py') "${SshAlias}:$RemoteRoot/scripts/remote_job.py"
if ($LASTEXITCODE) { throw 'Remote helper upload failed' }
$configPath = Join-Path $ExperimentRoot 'local_board.json'
$board = if (Test-Path -LiteralPath $configPath) {
    Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
} else { [pscustomobject]@{} }
$board | Add-Member -NotePropertyName sshAlias -NotePropertyValue $SshAlias -Force
$board | Add-Member -NotePropertyName remoteRoot -NotePropertyValue $RemoteRoot -Force
[IO.File]::WriteAllText($configPath, ($board | ConvertTo-Json) + "`n", [Text.UTF8Encoding]::new($false))

$markerStart = '# BEGIN PLD RK3588 WORKFLOW'
$markerEnd = '# END PLD RK3588 WORKFLOW'
$target = (Join-Path $PSScriptRoot 'rk.ps1').Replace("'", "''")
$block = "$markerStart`r`nfunction global:rk { & '$target' @args }`r`n$markerEnd`r`n"
$documents = [Environment]::GetFolderPath('MyDocuments')
$backupRoot = Join-Path $ProjectRoot ('.work\ssh_setup\' + (Get-Date -Format 'yyyyMMddTHHmmssfff'))
foreach ($edition in @('PowerShell','WindowsPowerShell')) {
    $profilePath = Join-Path $documents "$edition\profile.ps1"
    $old = if (Test-Path -LiteralPath $profilePath) { [IO.File]::ReadAllText($profilePath) } else { '' }
    $pattern = '(?ms)^' + [regex]::Escape($markerStart) + '\r?\n.*?^' + [regex]::Escape($markerEnd) + '\r?\n?'
    if ($old -match $pattern) {
        $new = [regex]::Replace($old, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block })
    } else {
        if ($old -match '(?i)function\s+(global:)?rk\b|Set-Alias\s+rk\b') {
            throw "Existing rk function/alias in $profilePath; refusing to overwrite it"
        }
        $new = $old.TrimEnd() + "`r`n`r`n" + $block
    }
    if ($new -ne $old) {
        New-Item -ItemType Directory -Force -Path (Split-Path $profilePath -Parent) | Out-Null
        if (Test-Path -LiteralPath $profilePath) {
            New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
            Copy-Item -LiteralPath $profilePath -Destination (Join-Path $backupRoot "$edition-profile.ps1")
        }
        [IO.File]::WriteAllText($profilePath, $new, [Text.UTF8Encoding]::new($false))
    }
    Write-Output "profile=$profilePath"
}
& (Join-Path $PSScriptRoot 'rk.ps1') check
if ($LASTEXITCODE) { throw 'Installed workflow check failed' }
Write-Output 'SETUP_PASS: reopen PowerShell, or reload your CurrentUserAllHosts profile, then use rk.'
