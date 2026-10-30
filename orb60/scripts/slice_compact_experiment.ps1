[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineLayer,
      [Parameter(Mandatory=$true)][string]$AcceptedDescriptor,
      [string]$Job='',[ValidateRange(1,16)][int]$Jobs=2)
. (Join-Path $PSScriptRoot 'environment.ps1')
$sliceBase=[IO.Path]::GetFullPath($BaselineLayer)
$slicePrior=Get-Content -LiteralPath (Join-Path $sliceBase 'status.json') -Raw | ConvertFrom-Json
if($slicePrior.State -ne 'SUCCEEDED' -or !$slicePrior.Cosim -or $slicePrior.PeriodNs -ne 8 -or
   $slicePrior.LayerPpc -ne 4 -or !$slicePrior.LayerIoOverlap -or !$slicePrior.LayerBramFifos) {throw 'Requires accepted8ns4PPC layer'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_slice_compact_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$sliceRoot=[IO.Path]::GetFullPath($Job)
if(Test-Path -LiteralPath (Join-Path $sliceRoot 'status.json')) {throw 'Refuse existing Slice experiment'}
$sliceAuthor=Join-Path $sliceRoot 'inputs_author';$sliceTools=Join-Path $sliceRoot 'inputs_tools'
New-Item -ItemType Directory -Path $sliceAuthor,$sliceTools -Force | Out-Null
foreach($item in Get-ChildItem -LiteralPath (Join-Path $Orb60Root 'experiments/slice_compact')) {Copy-Item -LiteralPath $item.FullName -Destination $sliceAuthor -Recurse}
foreach($name in @('slice_compact_experiment.ps1','slice_compact_hls.ps1','compare_slice_compact.py','compare_layer2.py','compare_hls.py','orb_timing.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $sliceTools
}
$sliceHashes=Get-ChildItem -LiteralPath $sliceRoot -File -Recurse | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($sliceRoot.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$sliceHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sliceRoot 'experiment_manifest.json') -Encoding UTF8
$sliceState=[ordered]@{State='RUNNING';Stage='HOST_EXACT';Job=$sliceRoot;ProcessId=$PID;BaselineLayer=$sliceBase;
    AcceptedDescriptor=$AcceptedDescriptor;FrequencyMHz=125;StartedUtc=[DateTime]::UtcNow.ToString('o');Candidates=@();
    Scope='Three bounded candidate-only key/storage probes, exact C/RTL and directional complete routed top for modes2/3; fixed published backend; random AXI/frame/bit/board separate'}
function Save-SliceExperiment {$sliceState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $sliceRoot 'status.json') -Encoding UTF8}
function Check-SliceExperiment {
    foreach($file in $sliceHashes) {if((Get-FileHash -LiteralPath (Join-Path $sliceRoot $file.Path)).Hash -ne $file.SHA256) {throw 'Frozen Slice experiment inputs changed'}}
    foreach($file in @('slice_compact_hls.ps1','orb_timing.ps1')) {
        if((Get-FileHash -LiteralPath (Join-Path $sliceTools $file)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $file)).Hash) {throw ('Live Slice launcher changed: '+$file)}
    }
}
Save-SliceExperiment;Write-Output "ORB60_SLICE_EXPERIMENT_JOB=$sliceRoot PID=$PID"
$sliceShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$sliceSource=Join-Path $sliceAuthor 'FPGA_ORB_HLS/fastv2/next'
$sliceRef=Join-Path $sliceAuthor 'FPGA_ORB_SHARED_v1.0'
$sliceFlags=@('-std=c++17','-O2','-Wno-unknown-pragmas','-Wno-unused-label',
    ('-I'+(Join-Path $sliceSource 'include')),('-I'+(Join-Path $sliceSource '../include')),('-I'+$sliceRef))
try {
    foreach($mode in @(1,2,3)) {
        Check-SliceExperiment
        $sliceState.Stage="HOST_EXACT_MODE$mode";Save-SliceExperiment
        $modeFlag="-DORB60_SLICE_COMPACT_MODE=$mode"
        & $Orb60Cxx @sliceFlags $modeFlag (Join-Path $sliceSource 'host/test_compact_tournament.cpp') -o (Join-Path $sliceRoot "key${mode}.exe") *> (Join-Path $sliceRoot "key${mode}_compile.log")
        if($LASTEXITCODE) {throw "Mode$mode compact key oracle build failed"}
        & (Join-Path $sliceRoot "key${mode}.exe") *> (Join-Path $sliceRoot "key${mode}.log")
        if($LASTEXITCODE) {throw "Mode$mode scalar ordering/full tie key mismatch"}
        & $Orb60Cxx @sliceFlags $modeFlag (Join-Path $sliceSource 'src/fastv2_hls.cpp') (Join-Path $sliceSource 'host/test_candidate_reducer.cpp') (Join-Path $sliceRef 'golden.cpp') -o (Join-Path $sliceRoot "grid${mode}.exe") *> (Join-Path $sliceRoot "grid${mode}_compile.log")
        if($LASTEXITCODE) {throw "Mode$mode original sorted-grid oracle build failed"}
        & (Join-Path $sliceRoot "grid${mode}.exe") *> (Join-Path $sliceRoot "grid${mode}.log")
        if($LASTEXITCODE) {throw "Mode$mode same-cell/tie/budget/capacity/guard mismatch"}
        $sliceState.Stage="HLS_PROBE_MODE$mode";Save-SliceExperiment
        & $sliceShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'slice_compact_hls.ps1') -Mode $mode -AuthorRoot $sliceAuthor -NoExport -JobFile (Join-Path $sliceRoot "probe${mode}_job.txt") *> (Join-Path $sliceRoot "probe${mode}.log")
        if($LASTEXITCODE) {throw "Mode$mode HLS exact CSim/synthesis failed"}
        $sliceState["Probe${mode}Job"]=(Get-Content -LiteralPath (Join-Path $sliceRoot "probe${mode}_job.txt") -Raw).Trim();Save-SliceExperiment
    }
    $sliceState.Stage='PROBE_STRUCTURE_COMPARE';Save-SliceExperiment;Check-SliceExperiment
    & $ProjectPython (Join-Path $sliceTools 'compare_slice_compact.py') --baseline $sliceBase --jobs $sliceState.Probe1Job $sliceState.Probe2Job $sliceState.Probe3Job --output (Join-Path $sliceRoot 'probe_comparison.json') *> (Join-Path $sliceRoot 'probe_compare.log')
    if($LASTEXITCODE) {throw 'Actual key widths/storage/bank recurrence/II/AXI mismatch'}
    foreach($mode in @(2,3)) {
        $row=[ordered]@{Mode=$mode;State='RUNNING';Stage='HLS_COSIM_IP'}
        $sliceState.Candidates+=@($row);$sliceState.Stage="ACCEPT_ROUTE_MODE$mode";Save-SliceExperiment;Check-SliceExperiment
        try {
            & $sliceShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'slice_compact_hls.ps1') -Mode $mode -SourceProbe $sliceState["Probe${mode}Job"] -Cosim -JobFile (Join-Path $sliceRoot "accepted${mode}_hls_job.txt") *> (Join-Path $sliceRoot "accepted${mode}_hls.log")
            if($LASTEXITCODE) {throw 'Compact candidate fresh C/RTL/IP failed'}
            $hls=(Get-Content -LiteralPath (Join-Path $sliceRoot "accepted${mode}_hls_job.txt") -Raw).Trim();$row['HlsJob']=$hls
            $carrier=Join-Path $sliceRoot "accepted_layer_mode$mode";New-Item -ItemType Directory -Path $carrier -Force | Out-Null
            & $ProjectPython (Join-Path $sliceTools 'compare_layer2.py') --job $hls --output (Join-Path $carrier 'comparison.json') *> (Join-Path $sliceRoot "accepted${mode}_compare.log")
            if($LASTEXITCODE) {throw 'All required real II/64bit/32bit gates failed'}
            [ordered]@{State='SUCCEEDED';layer2Job=$hls;PeriodNs=8;Scope='Exact21C/RTL and II/interface only; candidate protocol/frame separate'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $carrier 'status.json') -Encoding UTF8
            $row.Stage='COMPLETE_TOP_ROUTE';Save-SliceExperiment;Check-SliceExperiment
            & $sliceShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') -AcceptedLayer $carrier -AcceptedDescriptor $AcceptedDescriptor -FrequencyMHz 125 -Jobs $Jobs -ExtendedDiagnostics -JobFile (Join-Path $sliceRoot "route${mode}_job.txt") *> (Join-Path $sliceRoot "route${mode}.log")
            $routeCode=$LASTEXITCODE
            if(Test-Path -LiteralPath (Join-Path $sliceRoot "route${mode}_job.txt")) {$row['RouteJob']=(Get-Content -LiteralPath (Join-Path $sliceRoot "route${mode}_job.txt") -Raw).Trim()}
            if($routeCode) {throw 'Compact candidate full route hard gates failed; actual child evidence retained'}
            $routeState=Get-Content -LiteralPath (Join-Path $row.RouteJob 'status.json') -Raw | ConvertFrom-Json
            if($routeState.State -ne 'SUCCEEDED') {throw 'Route lacks authoritative acceptance'}
            $row['Timing']=$routeState.Timing;$row.State='SUCCEEDED';$row.Stage='DIRECTIONAL_ROUTE_COMPLETE'
        } catch {$row.State='FAILED';$row['Error']=$_.Exception.Message}
        Save-SliceExperiment
    }
    if(@($sliceState.Candidates | Where-Object State -NE 'SUCCEEDED').Count) {throw 'One or more directional candidates failed; all per-candidate evidence retained'}
    $sliceState.State='SUCCEEDED';$sliceState.Stage='DIRECTIONAL_ROUTES_COMPLETE'
} catch {$sliceState.State='FAILED';$sliceState['Error']=$_.Exception.Message;throw}
finally {$sliceState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-SliceExperiment}
