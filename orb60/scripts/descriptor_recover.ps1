[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$HlsJob,[string]$OriginalGate='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$descOrigin=[IO.Path]::GetFullPath($HlsJob)
$descOriginState=Get-Content -LiteralPath (Join-Path $descOrigin 'status.json') -Raw | ConvertFrom-Json
if($descOriginState.State -ne 'SUCCEEDED' -or !$descOriginState.Cosim -or $descOriginState.Kernel -ne 'descriptor' -or $descOriginState.PeriodNs -ne 10) {throw 'Requires completed exact descriptor HLS/RTL job'}
foreach($descSource in (Get-Content -LiteralPath (Join-Path $descOrigin 'source_manifest.json') -Raw | ConvertFrom-Json)) {
    if((Get-FileHash -LiteralPath (Join-Path $descOrigin ('inputs/'+$descSource.Path))).Hash -ne $descSource.SHA256) {throw 'Descriptor source snapshot changed'}
}
$descRecoveryName='{0}_descriptor_recovery_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$descRecoveryJob=Join-Path $Orb60Root "build/optimized/comparison/$descRecoveryName"
New-Item -ItemType Directory -Path $descRecoveryJob | Out-Null
$descRecoveryStatus=Join-Path $descRecoveryJob 'status.json'
$descRecoveryState=[ordered]@{State='RUNNING';Stage='VERIFY';Job=$descRecoveryJob;DescriptorHlsJob=$descOrigin;OriginalGate=$OriginalGate;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID;Scope='Fresh exact-II/AXI post-check only; no rerun or routed timing claim'}
$descRecoveryState | ConvertTo-Json | Set-Content -LiteralPath $descRecoveryStatus -Encoding UTF8
Write-Output "ORB60_DESCRIPTOR_RECOVERY_JOB=$descRecoveryJob"
try {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compare_descriptor.py') -Destination $descRecoveryJob
    & $ProjectPython (Join-Path $PSScriptRoot 'compare_descriptor.py') --job $descOrigin --output (Join-Path $descRecoveryJob 'comparison.json')
    if($LASTEXITCODE) {throw 'Descriptor actual-II/interface acceptance failed'}
    $descRecoveryState.State='SUCCEEDED';$descRecoveryState.Stage='COMPLETE'
} catch {$descRecoveryState.State='FAILED';$descRecoveryState['Error']=$_.Exception.Message;throw}
finally {$descRecoveryState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$descRecoveryState | ConvertTo-Json | Set-Content -LiteralPath $descRecoveryStatus -Encoding UTF8}
