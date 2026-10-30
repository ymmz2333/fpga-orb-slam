[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PairJob)
. (Join-Path $PSScriptRoot 'environment.ps1')
$bitPair=[IO.Path]::GetFullPath($PairJob)
$bitProof=Get-Content -LiteralPath (Join-Path $bitPair 'joint_result.json') -Raw|ConvertFrom-Json
if($bitProof.status -ne 'PASS' -or $bitProof.nominal_frequency_mhz -ne 150) {throw 'Requires complete accepted150MHz joint evidence'}
$bitOutput=Join-Path $bitPair 'bit';if(Test-Path -LiteralPath $bitOutput) {throw 'Refusing existing bit output'}
New-Item -ItemType Directory -Path $bitOutput|Out-Null
foreach($name in @('summarize_frequency_result.py','check_frequency_release.py')) {Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $bitOutput}
Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/write_frequency_bit.tcl') -Destination $bitOutput
Copy-Item -LiteralPath (Join-Path $bitProof.route 'inputs/timing_checks.tcl') -Destination $bitOutput
$bitState=[ordered]@{State='RUNNING';Stage='PAIR_CHECK';FrequencyMHz=150;StartedUtc=[DateTime]::UtcNow.ToString('o');Scope='Verified150MHz checkpoint bit only; PS FCLK input100MHz; no PS/board programming'}
function Save-FrequencyBit {$bitState|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $bitOutput 'status.json') -Encoding UTF8}
Save-FrequencyBit
try {
    & $ProjectPython (Join-Path $bitOutput 'summarize_frequency_result.py') --pair $bitPair --route $bitProof.route --frame $bitProof.frame --protocol $bitProof.protocol --output (Join-Path $bitOutput 'joint_validation.json') *> (Join-Path $bitOutput 'joint.log')
    if($LASTEXITCODE) {throw 'Fresh joint acceptance check failed'}
    & $ProjectPython (Join-Path $bitOutput 'check_frequency_release.py') --pair $bitPair --joint (Join-Path $bitOutput 'joint_validation.json') --output (Join-Path $bitOutput 'release_validation.json') *> (Join-Path $bitOutput 'pair.log')
    if($LASTEXITCODE) {throw 'Immutable source/IP/RTL/4GB pairing failed'}
    $bitValidation=Get-Content -LiteralPath (Join-Path $bitOutput 'release_validation.json') -Raw|ConvertFrom-Json
    $env:ORB60_BIT_CHECKPOINT=$bitValidation.checkpoint.Replace('\','/')
    $env:ORB60_BIT_OUTPUT=$bitOutput.Replace('\','/')
    $env:ORB60_BIT_TIMING_CHECKS=(Join-Path $bitOutput 'timing_checks.tcl').Replace('\','/')
    $bitState.Stage='WRITE_BITSTREAM';Save-FrequencyBit
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $bitOutput 'write_frequency_bit.tcl') -log (Join-Path $bitOutput 'vivado.log') -journal (Join-Path $bitOutput 'vivado.jou') *> (Join-Path $bitOutput 'tool.log')
    $bitExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
    if($bitExit -or !(Test-Path -LiteralPath (Join-Path $bitOutput 'success.stamp'))) {throw 'Verified-checkpoint bit generation failed'}
    if((Get-FileHash -LiteralPath $bitValidation.checkpoint).Hash.ToLowerInvariant() -ne $bitValidation.checkpoint_sha256) {throw 'Checkpoint changed while writing bit'}
    $bitState['BitSha256']=(Get-FileHash -LiteralPath (Join-Path $bitOutput 'orb60_150mhz.bit')).Hash
    $bitState.State='SUCCEEDED';$bitState.Stage='COMPLETE'
} catch {$bitState.State='FAILED';$bitState['Error']=$_.Exception.Message;throw}
finally {$bitState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-FrequencyBit}
