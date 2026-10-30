[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Vectors)
. (Join-Path $PSScriptRoot 'environment.ps1')
$vectorsRoot=[IO.Path]::GetFullPath($Vectors)
$oracle=Get-Content -LiteralPath (Join-Path $vectorsRoot 'vectors.json') -Raw | ConvertFrom-Json
if($oracle.bins.Count -ne 32 -or $oracle.cases.Count -ne 38) {throw 'Requires complete independent descriptor vectors'}
foreach($entry in $oracle.sha256.PSObject.Properties) {
    if((Get-FileHash -LiteralPath (Join-Path $vectorsRoot $entry.Name)).Hash.ToLowerInvariant() -ne $entry.Value) {throw 'Oracle input changed'}
}
$name='{0}_descriptor_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/optimized/comparison/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='NATIVE_EXACT';Job=$job;Vectors=$vectorsRoot;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_DESCRIPTOR_GATE_JOB=$job"
Write-Output "ORB60_DESCRIPTOR_GATE_PID=$PID"
try {
    & (Join-Path $Orb60Root 'build/optimized/host/next_descriptor_stream_test.exe') $vectorsRoot | Tee-Object -FilePath (Join-Path $job 'native.log')
    if($LASTEXITCODE) {throw 'Independent Python/native descriptor gate failed'}
    $state.Stage='HLS_DESCRIPTOR';$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    # Isolate the child runner's PowerShell scope/state from this gate wrapper.
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -DescriptorVectors $vectorsRoot -Cosim 2>&1 | Tee-Object -FilePath (Join-Path $job 'descriptor.log')
    if($LASTEXITCODE) {throw 'Descriptor HLS child process failed'}
    $child=Get-ChildItem -LiteralPath (Join-Path $Orb60Root 'build/optimized/hls') -Directory -Filter '*_descriptor_*' | Sort-Object CreationTimeUtc -Descending | Select-Object -First 1
    if(!$child) {throw 'Missing descriptor HLS job'}
    $childState=Get-Content -LiteralPath (Join-Path $child.FullName 'status.json') -Raw | ConvertFrom-Json
    if($childState.State -ne 'SUCCEEDED' -or !$childState.Cosim -or $childState.Kernel -ne 'descriptor' -or [DateTime]$childState.StartedUtc -lt [DateTime]$state.StartedUtc) {throw 'Incomplete/stale descriptor job'}
    $state['DescriptorHlsJob']=$child.FullName;$state.Stage='COMPARE';$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compare_descriptor.py') -Destination $job
    & $ProjectPython (Join-Path $PSScriptRoot 'compare_descriptor.py') --job $child.FullName --output (Join-Path $job 'comparison.json')
    if($LASTEXITCODE) {throw 'Descriptor actual-II/interface post-check failed'}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
