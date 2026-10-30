[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineHlsJob,
      [string]$ReuseResizeJob, [string]$PreviousFrontJob, [switch]$RequireReducerII1)
. (Join-Path $PSScriptRoot 'environment.ps1')
$baseline=[IO.Path]::GetFullPath($BaselineHlsJob)
$kernels=@('front','resize')
if ($ReuseResizeJob) {
    $resize=[IO.Path]::GetFullPath($ReuseResizeJob)
    $resizeState=Get-Content -LiteralPath (Join-Path $resize 'status.json') -Raw | ConvertFrom-Json
    if ($resizeState.State -ne 'SUCCEEDED' -or !$resizeState.Cosim -or $resizeState.Kernel -ne 'resize' -or $resizeState.PeriodNs -ne 10) {throw 'Resize reuse requires an accepted 10 ns co-simulation job'}
    $manifest=Get-Content -LiteralPath (Join-Path $resize 'source_manifest.json') -Raw | ConvertFrom-Json
    foreach ($relative in @('FPGA_ORB_HLS/fastv2/next/src/resize_hls.cpp','FPGA_ORB_HLS/fastv2/include/fastv2.hpp','FPGA_ORB_HLS/fastv2/include/fastv2_profile_rom.hpp')) {
        $record=@($manifest | Where-Object { $_.Path.Replace('\','/') -eq $relative })
        if ($record.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $Orb60Root "optimized/$relative")).Hash -ne $record[0].SHA256) {throw "Resize input changed: $relative"}
    }
    $kernels=@('front')
}
$name='{0}_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/optimized/comparison/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='HOST';Job=$job;BaselineHlsJob=$baseline;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
if ($ReuseResizeJob) {$state['resizeJob']=$resize;$state['resizeReused']=$true}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_OPTIMIZATION_JOB=$job"
try {
    & (Join-Path $PSScriptRoot 'host.ps1') -Variant optimized *>&1 | Tee-Object -FilePath (Join-Path $job 'host.log')
    foreach ($kernel in $kernels) {
        $state.Stage="HLS_$($kernel.ToUpper())"
        $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
        & (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel $kernel -Cosim *>&1 | Tee-Object -FilePath (Join-Path $job "$kernel.log")
        $kernelRoot=Join-Path $Orb60Root 'build/optimized/hls'
        $child=Get-ChildItem -LiteralPath $kernelRoot -Directory | Sort-Object CreationTimeUtc -Descending | Select-Object -First 1
        $childState=Get-Content -LiteralPath (Join-Path $child.FullName 'status.json') -Raw | ConvertFrom-Json
        if ($childState.State -ne 'SUCCEEDED' -or $childState.Kernel -ne $kernel) {throw "Incomplete $kernel HLS child"}
        $state["${kernel}Job"]=$child.FullName
        $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    }
    $state.Stage='COMPARE'
    $comparisonArgs=@((Join-Path $PSScriptRoot 'compare_hls.py'),'--baseline',$baseline,'--front',$state.frontJob,'--resize',$state.resizeJob,'--output',(Join-Path $job 'comparison.json'))
    if ($PreviousFrontJob) {$comparisonArgs += @('--previous-front',[IO.Path]::GetFullPath($PreviousFrontJob))}
    & $ProjectPython @comparisonArgs
    if ($LASTEXITCODE -ne 0) {throw 'Comparison post-check failed'}
    if ($RequireReducerII1) {
        $proof=Get-Content -LiteralPath (Join-Path $job 'comparison.json') -Raw | ConvertFrom-Json
        $ii=$proof.kernels.front.optimized.pipelined_loops.ReduceCandidateTokens.II
        if ($ii -ne 1) {throw "Candidate reducer throughput target failed: actual II=$ii, required II=1"}
    }
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
