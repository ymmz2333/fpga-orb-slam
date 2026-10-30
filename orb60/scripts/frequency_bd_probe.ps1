[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$LayerHlsJob,[Parameter(Mandatory=$true)][string]$DescriptorHlsJob,
      [ValidateRange(125,200)][double]$FrequencyMHz=150,[ValidateSet(0,1,7)][int]$ControlSliceMode=7,[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$probeId=[guid]::NewGuid().ToString('N').Substring(0,8)
$probeRoot=Join-Path $Orb60Root "build/optimized/gates/$(Get-Date -Format yyyyMMdd_HHmmss)_frequency_bd_$probeId"
$probeScratch=Join-Path $VivadoBuildRoot "orb60/f$probeId"
New-Item -ItemType Directory -Path (Join-Path $probeRoot 'inputs'),(Join-Path $probeScratch 'inputs'),(Join-Path $probeScratch 'ip') -Force | Out-Null
foreach($file in @('ps_config.tcl','build_orb_frequency.tcl')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$file") -Destination (Join-Path $probeRoot "inputs/$file")
    Copy-Item -LiteralPath (Join-Path $probeRoot "inputs/$file") -Destination (Join-Path $probeScratch "inputs/$file")
}
foreach($core in @('layer','desc')) {
    $hls=if($core -eq 'layer') {$LayerHlsJob} else {$DescriptorHlsJob}
    $kernel=if($core -eq 'layer') {'layer2'} else {'descriptor'}
    $state=Get-Content -LiteralPath (Join-Path $hls 'status.json') -Raw | ConvertFrom-Json
    if($state.State -ne 'SUCCEEDED' -or !$state.Cosim -or $state.Kernel -ne $kernel) {throw 'BD probe requires accepted source IP'}
    Copy-Item -LiteralPath (Join-Path $hls "projects/$kernel/solution1/impl/ip") -Destination (Join-Path $probeScratch "ip/$core") -Recurse
}
$probeState=[ordered]@{State='RUNNING';Scope='AMD clock/register slice block-design configuration validation only; no synthesis/route/RTL protocol result';Scratch=$probeScratch;Job=$probeRoot;FrequencyMHz=$FrequencyMHz;ControlSliceMode=$ControlSliceMode;LayerHlsJob=$LayerHlsJob;DescriptorHlsJob=$DescriptorHlsJob}
function Save-Probe {$probeState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $probeRoot 'status.json') -Encoding UTF8}
Save-Probe;if($JobFile) {$probeRoot | Set-Content -LiteralPath $JobFile -Encoding UTF8}
$env:ORB60_ORB_TIMING_ROOT=$probeScratch.Replace('\','/');$env:ORB60_ORB_TIMING_JOBS=2
$env:ORB60_ORB_TIMING_FREQUENCY=$FrequencyMHz.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
$env:ORB60_CONTROL_SLICE_MODE=$ControlSliceMode;$env:ORB60_FREQUENCY_VALIDATE_ONLY=1
try {
    & $VivadoBat -mode batch -source (Join-Path $probeScratch 'inputs/build_orb_frequency.tcl') -log (Join-Path $probeRoot 'vivado.log') -journal (Join-Path $probeRoot 'vivado.jou') *> (Join-Path $probeRoot 'console.log')
    if($LASTEXITCODE -or !(Select-String -LiteralPath (Join-Path $probeRoot 'console.log') -Pattern '^FREQUENCY_BD_VALIDATE_PASS')) {throw 'Frequency AMD block-design validation failed'}
    Copy-Item -LiteralPath (Join-Path $probeScratch 'vivado/post_clock_config.tsv') -Destination $probeRoot
    $probeState.State='SUCCEEDED';Write-Output "FREQUENCY_BD_VALIDATE_PASS $probeRoot"
} catch {$probeState.State='FAILED';$probeState['Error']=$_.Exception.Message;throw}
finally {Save-Probe}
