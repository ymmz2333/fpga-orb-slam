[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$TimingJob,[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$diagPrior=Get-Content -LiteralPath (Join-Path $TimingJob 'status.json') -Raw | ConvertFrom-Json
if($diagPrior.State -ne 'SUCCEEDED' -or $diagPrior.FrequencyMHz -ne 100 -or $diagPrior.Part -ne 'xc7z015clg485-2') {throw 'Requires retained accepted 100 MHz routed top'}
$diagCheckpoint=Join-Path $diagPrior.ScratchRoot 'vivado/next_system_routed.dcp'
$diagHash=(Get-FileHash -LiteralPath $diagCheckpoint).Hash
$diagId=[guid]::NewGuid().ToString('N').Substring(0,8)
$diagJob=Join-Path $Orb60Root ('build/optimized/diagnostics/{0}_routed_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$diagId)
$diagScratch=Join-Path $VivadoBuildRoot "orb60/d$diagId"
if(Test-Path -LiteralPath $diagScratch) {throw 'Refusing existing diagnostic scratch'}
$diagInputs=Join-Path $diagJob 'inputs';$diagReports=Join-Path $diagJob 'reports'
New-Item -ItemType Directory -Path $diagInputs,$diagReports,$diagScratch -Force | Out-Null
foreach($diagFile in @('checkpoint_diagnostics.tcl','diagnostic_reports.tcl')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$diagFile") -Destination $diagInputs
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'summarize_diagnostics.py') -Destination $diagInputs
$diagManifest=Get-ChildItem -LiteralPath $diagInputs -File | ForEach-Object {
    [ordered]@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$diagManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $diagJob 'tool_manifest.json') -Encoding UTF8
$diagState=[ordered]@{State='RUNNING';Stage='VIVADO_REPORTS';Job=$diagJob;ProcessId=$PID;
    TimingJob=[IO.Path]::GetFullPath($TimingJob);Checkpoint=$diagCheckpoint;CheckpointSHA256=$diagHash;
    Scope='Read-only retained routed DCP diagnostics; no new route or board acceptance';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-DiagnosticState {$diagState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $diagJob 'status.json') -Encoding UTF8}
Save-DiagnosticState
if($JobFile) {$diagJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
Write-Output "ORB60_DIAGNOSTIC_JOB=$diagJob PID=$PID"
$env:ORB60_DIAGNOSTIC_CHECKPOINT=$diagCheckpoint.Replace('\','/')
$env:ORB60_DIAGNOSTIC_REPORTS=$diagReports.Replace('\','/')
Push-Location $diagScratch
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $diagInputs 'checkpoint_diagnostics.tcl') -log (Join-Path $diagJob 'vivado.log') -journal (Join-Path $diagJob 'vivado.jou')
    $diagCode=$LASTEXITCODE;$ErrorActionPreference='Stop'
    if($diagCode -or !(Test-Path -LiteralPath (Join-Path $diagReports 'success.stamp'))) {throw "Checkpoint diagnostic export failed (exit $diagCode)"}
    $diagState.Stage='SUMMARY';Save-DiagnosticState
    & $ProjectPython (Join-Path $diagInputs 'summarize_diagnostics.py') $diagReports
    if($LASTEXITCODE) {throw 'Incomplete or inconsistent diagnostic statistics'}
    if((Get-FileHash -LiteralPath $diagCheckpoint).Hash -ne $diagHash) {throw 'Original checkpoint changed'}
    $diagState.State='SUCCEEDED';$diagState.Stage='COMPLETE'
} catch {$diagState.State='FAILED';$diagState['Error']=$_.Exception.Message;throw}
finally {
    Pop-Location
    $diagState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-DiagnosticState
}
