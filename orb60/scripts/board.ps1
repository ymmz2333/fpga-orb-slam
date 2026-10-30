[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$HlsJob, [ValidateRange(1,16)][int]$Jobs=4, [switch]$SetupOnly)
. (Join-Path $PSScriptRoot 'environment.ps1')
$hls = [IO.Path]::GetFullPath($HlsJob)
$allowed = [IO.Path]::GetFullPath((Join-Path $Orb60Root 'build')) + '\'
if (!$hls.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)) { throw 'HLS job must belong to orb60/build' }
$hlsState = Get-Content -LiteralPath (Join-Path $hls 'status.json') -Raw | ConvertFrom-Json
if ($hlsState.State -ne 'SUCCEEDED' -or $hlsState.Kernel -ne 'all' -or !$hlsState.Cosim) { throw 'All three cosim/IP gates must pass first' }
$name='{0}_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/$($hlsState.Variant)/board/$name"
$inputs=Join-Path $job 'inputs'
New-Item -ItemType Directory -Path $inputs -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/ps_config.tcl') -Destination $inputs
foreach ($file in @('build_system.tcl','timing_checks.tcl','route_reports.tcl')) { Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$file") -Destination $inputs }
Copy-Item -LiteralPath (Join-Path $hls 'projects') -Destination $job -Recurse
Copy-Item -LiteralPath (Join-Path $hls 'source_manifest.json') -Destination (Join-Path $job 'hls_source_manifest.json')
$env:NEXT_BOARD_ROOT=$job.Replace('\','/')
$env:NEXT_BOARD_JOBS=$Jobs
$env:NEXT_BOARD_SETUP_ONLY=[int][bool]$SetupOnly
$env:NEXT_BOARD_FREQUENCY_MHZ=(1000.0 / $hlsState.PeriodNs).ToString([Globalization.CultureInfo]::InvariantCulture)
$state=[ordered]@{State='RUNNING';Job=$job;HlsJob=$hls;SetupOnly=[bool]$SetupOnly;Part=$hlsState.Part;PeriodNs=$hlsState.PeriodNs;StartedUtc=[DateTime]::UtcNow.ToString('o')}
$state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job 'status.json') -Encoding UTF8
Write-Output "ORB60_BOARD_JOB=$job"
Push-Location $job
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $inputs 'build_system.tcl') -log (Join-Path $job 'vivado.log') -journal (Join-Path $job 'vivado.jou')
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    $stamp=if ($SetupOnly) {'.vivado_setup_success'} else {'.vivado_success'}
    if ($code -ne 0 -or !(Test-Path -LiteralPath (Join-Path $job "vivado/$stamp"))) { throw "Vivado failed (exit $code)" }
    $state.State='SUCCEEDED'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {Pop-Location;$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job 'status.json') -Encoding UTF8}
