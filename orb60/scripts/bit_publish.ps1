[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AcceptedRoute,
      [Parameter(Mandatory=$true)][string]$Repository,[switch]$Push)
. (Join-Path $PSScriptRoot 'environment.ps1')
$bitRoute=[IO.Path]::GetFullPath($AcceptedRoute);$bitRepo=[IO.Path]::GetFullPath($Repository)
$bitAccepted=Get-Content -LiteralPath (Join-Path $bitRoute 'status.json') -Raw | ConvertFrom-Json
if($bitAccepted.State -ne 'SUCCEEDED' -or $bitAccepted.FrequencyMHz -ne 100 -or $bitAccepted.Part -ne 'xc7z015clg485-2') {throw 'Requires the accepted complete 100 MHz route'}
$bitCheckpoint=Join-Path $bitAccepted.ScratchRoot 'vivado/next_system_routed.dcp'
$bitHash=(Get-FileHash -LiteralPath $bitCheckpoint).Hash
$bitName='{0}_bit_publication_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$bitJob=Join-Path $Orb60Root "build/optimized/publication/$bitName"
$bitInputs=Join-Path $bitJob 'inputs';$bitOutput=Join-Path $bitJob 'bit'
New-Item -ItemType Directory -Path $bitInputs,$bitOutput -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/write_accepted_bit.tcl') -Destination $bitInputs
Copy-Item -LiteralPath (Join-Path $bitRoute 'inputs/timing_checks.tcl') -Destination $bitInputs
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'finish_publication.py') -Destination $bitInputs
$env:ORB60_BIT_CHECKPOINT=$bitCheckpoint.Replace('\','/');$env:ORB60_BIT_OUTPUT=$bitOutput.Replace('\','/')
$env:ORB60_BIT_TIMING_CHECKS=(Join-Path $bitInputs 'timing_checks.tcl').Replace('\','/')
$env:GIT_TERMINAL_PROMPT='0';$env:GCM_INTERACTIVE='Never'
$bitState=[ordered]@{State='RUNNING';Stage='WRITE_BITSTREAM';ProcessId=$PID;Job=$bitJob;
    AcceptedRoute=$bitRoute;CheckpointSha256=$bitHash;Repository=$bitRepo;StartedUtc=[DateTime]::UtcNow.ToString('o');
    Scope='Generate accepted 100 MHz bit, publish source/docs/evidence and complete fallback ZIP; no PS changes or programming'}
$bitStatus=Join-Path $bitJob 'status.json'
function Save-BitState {$bitState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $bitStatus -Encoding UTF8}
Save-BitState
Write-Output "ORB60_BIT_PUBLICATION_JOB=$bitJob PID=$PID"
try {
    Push-Location $bitJob
    try {
        $ErrorActionPreference='Continue'
        & $VivadoBat -mode batch -source (Join-Path $bitInputs 'write_accepted_bit.tcl') -log (Join-Path $bitJob 'vivado.log') -journal (Join-Path $bitJob 'vivado.jou') *> (Join-Path $bitJob 'tool.log')
        $bitExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
    } finally {Pop-Location}
    if($bitExit -or !(Test-Path -LiteralPath (Join-Path $bitOutput 'success.stamp'))) {throw 'Bitstream gate failed; inspect tool.log'}
    if((Get-FileHash -LiteralPath $bitCheckpoint).Hash -ne $bitHash) {throw 'Accepted checkpoint changed'}
    $bitState['BitstreamGenerated']=$true;$bitState.Stage='PACKAGE_COMMIT_PUSH';Save-BitState
    $bitArgs=@((Join-Path $bitInputs 'finish_publication.py'),'--root',$ProjectRoot,'--repo',$bitRepo,'--output',$bitJob,'--checkpoint',$bitCheckpoint)
    if($Push) {$bitArgs+='--push'}
    $ErrorActionPreference='Continue'
    & $ProjectPython -X utf8 @bitArgs *> (Join-Path $bitJob 'publication.log')
    $bitPublishExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
    if($bitPublishExit) {throw 'Publication/package verification failed; inspect publication.log'}
    $bitResult=Get-Content -LiteralPath (Join-Path $bitJob 'publication_result.json') -Raw | ConvertFrom-Json
    $bitState['Publication']=$bitResult;$bitState.State='SUCCEEDED';$bitState.Stage='COMPLETE'
    Write-Output "ORB60_BIT_PUBLICATION_PASS zip=$($bitResult.zip) github_pushed=$($bitResult.github_pushed)"
} catch {$bitState.State='FAILED';$bitState['Error']=$_.Exception.Message;throw}
finally {$bitState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-BitState}
