[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$IntegratedJob)
. (Join-Path $PSScriptRoot 'environment.ps1')
$verifiedRoot=[IO.Path]::GetFullPath($IntegratedJob)
$verifiedState=Get-Content -LiteralPath (Join-Path $verifiedRoot 'status.json') -Raw | ConvertFrom-Json
$verifiedRoute=Get-Content -LiteralPath (Join-Path $verifiedState.RouteJob 'status.json') -Raw | ConvertFrom-Json
$verifiedFrequency=[int]$verifiedRoute.FrequencyMHz
if($verifiedFrequency -notin @(100,125)) {throw 'Unsupported accepted release clock'}
$verifiedOutput=Join-Path $verifiedRoot 'bit';if(Test-Path -LiteralPath $verifiedOutput) {throw 'Refusing existing bit output'}
New-Item -ItemType Directory -Path $verifiedOutput | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'check_joint_release.py') -Destination $verifiedOutput
Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/write_accepted_bit.tcl') -Destination $verifiedOutput
Copy-Item -LiteralPath (Join-Path $verifiedState.RouteJob 'inputs/timing_checks.tcl') -Destination $verifiedOutput
$verifiedBitState=[ordered]@{State='RUNNING';Stage='PAIR_CHECK';ProcessId=$PID;FrequencyMHz=$verifiedFrequency;StartedUtc=[DateTime]::UtcNow.ToString('o');Scope="Immutable passed4PPC${verifiedFrequency}MHz computer candidate bit only; no PS/board programming"}
function Save-VerifiedBit {$verifiedBitState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $verifiedOutput 'status.json') -Encoding UTF8}
Save-VerifiedBit;Write-Output "VERIFIED4_BIT_PID=$PID OUTPUT=$verifiedOutput"
try {
    & $ProjectPython (Join-Path $verifiedOutput 'check_joint_release.py') --job $verifiedRoot --output (Join-Path $verifiedOutput 'joint_validation.json') *> (Join-Path $verifiedOutput 'pair.log')
    if($LASTEXITCODE) {throw 'Paired route/frame/source validation failed'}
    $verifiedPair=Get-Content -LiteralPath (Join-Path $verifiedOutput 'joint_validation.json') -Raw | ConvertFrom-Json
    $verifiedCheckpoint=Join-Path $verifiedRoute.ScratchRoot 'vivado/next_system_routed.dcp'
    $env:ORB60_BIT_CHECKPOINT=$verifiedCheckpoint.Replace('\','/');$env:ORB60_BIT_OUTPUT=$verifiedOutput.Replace('\','/')
    $env:ORB60_BIT_TIMING_CHECKS=(Join-Path $verifiedOutput 'timing_checks.tcl').Replace('\','/')
    $env:ORB60_BIT_FREQUENCY=$verifiedFrequency
    $verifiedBitState.Stage='WRITE_BITSTREAM';Save-VerifiedBit
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $verifiedOutput 'write_accepted_bit.tcl') -log (Join-Path $verifiedOutput 'vivado.log') -journal (Join-Path $verifiedOutput 'vivado.jou') *> (Join-Path $verifiedOutput 'tool.log')
    $verifiedExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
    if($verifiedExit -or !(Test-Path -LiteralPath (Join-Path $verifiedOutput 'success.stamp'))) {throw 'Passed-checkpoint bit generation failed'}
    if((Get-FileHash -LiteralPath $verifiedCheckpoint).Hash.ToLowerInvariant() -ne $verifiedPair.checkpoint_sha256) {throw 'Checkpoint changed while generating bit'}
    $verifiedBitState['BitSha256']=(Get-FileHash -LiteralPath (Join-Path $verifiedOutput "orb60_${verifiedFrequency}mhz.bit")).Hash
    $verifiedBitState.State='SUCCEEDED';$verifiedBitState.Stage='COMPLETE'
} catch {$verifiedBitState.State='FAILED';$verifiedBitState['Error']=$_.Exception.Message;throw}
finally {$verifiedBitState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-VerifiedBit}
