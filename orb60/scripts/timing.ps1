[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AcceptedComparison,
      [Parameter(Mandatory=$true)][string]$ResizeHlsJob,
      [Parameter(Mandatory=$true)][string]$GaussianHlsJob,
      [ValidateRange(1,16)][int]$Jobs=4)
. (Join-Path $PSScriptRoot 'environment.ps1')
$accepted=[IO.Path]::GetFullPath($AcceptedComparison)
$comparisonState=Get-Content -LiteralPath (Join-Path $accepted 'status.json') -Raw | ConvertFrom-Json
$comparison=Get-Content -LiteralPath (Join-Path $accepted 'comparison.json') -Raw | ConvertFrom-Json
if ($comparisonState.State -ne 'SUCCEEDED' -or !$comparison.throughput_gate_pass) {throw 'Requires accepted 2PPC functional/II evidence'}
$entries=@(
    @{Name='front';Kernel='front2';Job=$comparisonState.front2Job;Top='fastv2_front2_hls'},
    @{Name='resize';Kernel='resize';Job=[IO.Path]::GetFullPath($ResizeHlsJob);Top='fastv2_resize_hls'},
    @{Name='gaussian';Kernel='gaussian';Job=[IO.Path]::GetFullPath($GaussianHlsJob);Top='fastv2_gaussian_hls'}
)
$allowed=[IO.Path]::GetFullPath((Join-Path $Orb60Root 'build')) + '\'
foreach ($entry in $entries) {
    if (!$entry.Job.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)) {throw 'HLS inputs must belong to orb60/build'}
    $hlsState=Get-Content -LiteralPath (Join-Path $entry.Job 'status.json') -Raw | ConvertFrom-Json
    if ($hlsState.State -ne 'SUCCEEDED' -or !$hlsState.Cosim -or $hlsState.PeriodNs -ne 10 -or $hlsState.Part -ne 'xc7z015clg485-2' -or $hlsState.Kernel -notin @('all',$entry.Kernel)) {
        throw "Missing accepted 100 MHz functional evidence for $($entry.Name)"
    }
    $entry['Ip']=Join-Path $entry.Job "projects/$($entry.Kernel)/solution1/impl/ip"
    $component=Get-Content -LiteralPath (Join-Path $entry.Ip 'component.xml') -Raw
    if ($component -notmatch "<[^>]*name>$($entry.Top)</[^>]*name>") {throw "Packaged IP name mismatch: $($entry.Name)"}
    $manifest=Get-Content -LiteralPath (Join-Path $entry.Job 'source_manifest.json') -Raw | ConvertFrom-Json
    foreach ($record in $manifest) {
        if ((Get-FileHash -LiteralPath (Join-Path (Join-Path $entry.Job 'inputs') $record.Path)).Hash -ne $record.SHA256) {throw "Modified accepted source: $($record.Path)"}
    }
}
$shortId=[guid]::NewGuid().ToString('N').Substring(0,8)
$name='{0}_front2_100mhz_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$shortId
$job=Join-Path $Orb60Root "build/optimized/timing/$name"
$inputs=Join-Path $job 'inputs'
New-Item -ItemType Directory -Path $inputs -Force | Out-Null
# Archive names remain descriptive; all live Vivado paths use the configured
# short scratch root. Legacy Windows IP generation still has a 260-byte limit.
$scratch=Join-Path $VivadoBuildRoot "orb60/t$shortId"
if (Test-Path -LiteralPath $scratch) {throw 'Refusing to reuse an existing timing scratch directory'}
$liveInputs=Join-Path $scratch 'inputs'
New-Item -ItemType Directory -Path $liveInputs -Force | Out-Null
foreach ($file in @('build_system.tcl','timing_checks.tcl','route_reports.tcl','ps_config.tcl')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$file") -Destination $inputs
    Copy-Item -LiteralPath (Join-Path $inputs $file) -Destination $liveInputs
}
$maxPathBytes=0
foreach ($entry in $entries) {
    $destination=Join-Path $scratch "projects/$($entry.Name)/solution1/impl"
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -LiteralPath $entry.Ip -Destination $destination -Recurse
    Copy-Item -LiteralPath (Join-Path $entry.Job 'source_manifest.json') -Destination (Join-Path $inputs "$($entry.Name)_source_manifest.json")
    foreach ($file in Get-ChildItem -LiteralPath $entry.Ip -Recurse -File) {
        $relative=$file.FullName.Substring($entry.Ip.Length+1)
        $generated=Join-Path $scratch "vivado/p.gen/sources_1/bd/s/ip/s_fastv2_$($entry.Name)_0/$relative"
        $bytes=[Text.Encoding]::UTF8.GetByteCount($generated)
        $maxPathBytes=[Math]::Max($maxPathBytes,$bytes)
        if ($bytes -ge 240) {throw "Generated path lacks Windows length headroom ($bytes bytes): $generated"}
    }
}
$ipManifest=Get-ChildItem -LiteralPath (Join-Path $scratch 'projects') -File -Recurse | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($scratch.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$ipManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $inputs 'ip_manifest.json') -Encoding UTF8
$env:NEXT_BOARD_ROOT=$scratch.Replace('\','/')
$env:NEXT_BOARD_JOBS=$Jobs
$env:NEXT_BOARD_SETUP_ONLY=0
$env:NEXT_BOARD_FREQUENCY_MHZ=100
$env:NEXT_BOARD_FRONT_TOP='fastv2_front2_hls'
$env:NEXT_BOARD_TIMING_ONLY=1
$env:NEXT_BOARD_SHORT_NAMES=1
$state=[ordered]@{State='RUNNING';Stage='VIVADO_ROUTE';Job=$job;ScratchRoot=$scratch;MaximumPredictedIpPathBytes=$maxPathBytes;Inputs=$entries;Scope='Bounded timing experiment, not a release; full randomized AXI pending';Part='xc7z015clg485-2';FrequencyMHz=100;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_TIMING_JOB=$job"
Write-Output "ORB60_TIMING_SCRATCH=$scratch MAX_IP_PATH_BYTES=$maxPathBytes"
Push-Location $scratch
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $liveInputs 'build_system.tcl') -log (Join-Path $job 'vivado.log') -journal (Join-Path $job 'vivado.jou')
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if ($code -ne 0 -or !(Test-Path -LiteralPath (Join-Path $scratch 'vivado/.vivado_timing_success'))) {throw "Vivado timing experiment failed (exit $code); retained reports may contain measured violations"}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {
    Pop-Location
    $reportArchive=Join-Path $job 'reports'
    New-Item -ItemType Directory -Path $reportArchive -Force | Out-Null
    $liveReports=Join-Path $scratch 'vivado'
    if (Test-Path -LiteralPath $liveReports) {
        foreach ($report in Get-ChildItem -LiteralPath $liveReports -Filter 'post_*' -File) {
            Copy-Item -LiteralPath $report.FullName -Destination $reportArchive
        }
    }
    $metricFile=Join-Path $reportArchive 'post_route_metrics.tsv'
    if (Test-Path -LiteralPath $metricFile) {
        $metrics=[ordered]@{}
        foreach ($line in Get-Content -LiteralPath $metricFile) {
            $fields=$line -split "`t",2
            if ($fields.Count -eq 2) {$metrics[$fields[0]]=$fields[1]}
        }
        $state['Timing']=$metrics
    }
    $state['FinishedUtc']=[DateTime]::UtcNow.ToString('o')
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $status -Encoding UTF8
}
