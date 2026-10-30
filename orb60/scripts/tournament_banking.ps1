[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineAcceptedLayer,
      [Parameter(Mandatory=$true)][string]$Front2Hls,[string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$bankShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$bankPrior=Get-Content -LiteralPath (Join-Path $BaselineAcceptedLayer 'status.json') -Raw | ConvertFrom-Json
if($bankPrior.State -ne 'SUCCEEDED') {throw 'Accepted baseline layer gate is required'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_tournament_banks2_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$bankJob=[IO.Path]::GetFullPath($Job)
if(Test-Path -LiteralPath (Join-Path $bankJob 'status.json')) {throw 'Refusing an existing banking job'}
$bankInputs=Join-Path $bankJob 'inputs';New-Item -ItemType Directory -Path $bankInputs -Force | Out-Null
foreach($bankFile in @('tournament_banking.ps1','hls.ps1','hls.tcl','host.ps1','environment.ps1','compare_layer2.py','compare_hls.py','compare_tournament_banks.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $bankFile) -Destination $bankInputs
}
Copy-Item -LiteralPath (Join-Path $BaselineAcceptedLayer 'comparison.json') -Destination (Join-Path $bankInputs 'baseline_comparison.json')
$bankTools=Get-ChildItem -LiteralPath $bankInputs -File | ForEach-Object {
    [ordered]@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$bankTools | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $bankJob 'tool_manifest.json') -Encoding UTF8
$bankState=[ordered]@{State='RUNNING';Stage='HOST';Job=$bankJob;ProcessId=$PID;FrequencyMHz=100;
    BaselineAcceptedLayer=$BaselineAcceptedLayer;Front2Hls=$Front2Hls;
    Scope='Explicit parity-bank tournament candidate; custom HLS, exact 2PPC algorithm/interfaces; protocol/frame/route pending';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-BankingState {$bankState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $bankJob 'status.json') -Encoding UTF8}
Save-BankingState
Write-Output "ORB60_TOURNAMENT_BANKING_JOB=$bankJob PID=$PID"
try {
    & $bankShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'host.ps1') -Variant optimized *> (Join-Path $bankJob 'host.log')
    if($LASTEXITCODE) {throw 'Host exact regression failed'}
    $bankState.Stage='HLS_LAYER2';Save-BankingState
    $bankChildFile=Join-Path $bankJob 'hls_job.txt'
    & $bankShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel layer2 -Period 10 -Cosim -JobFile $bankChildFile *> (Join-Path $bankJob 'hls.log')
    if($LASTEXITCODE) {throw 'Parity-bank HLS/C-RTL gate failed'}
    $bankChild=(Get-Content -LiteralPath $bankChildFile -Raw).Trim();$bankState['LayerHlsJob']=$bankChild
    $bankState.Stage='COMPARE';Save-BankingState
    & $ProjectPython (Join-Path $bankInputs 'compare_layer2.py') --job $bankChild --front2 $Front2Hls --output (Join-Path $bankJob 'comparison.json') *> (Join-Path $bankJob 'compare.log')
    if($LASTEXITCODE) {throw 'Real score-bank II/interface gate failed'}
    & $ProjectPython (Join-Path $bankInputs 'compare_tournament_banks.py') --new (Join-Path $bankJob 'comparison.json') --old (Join-Path $bankInputs 'baseline_comparison.json') --output (Join-Path $bankJob 'banking_comparison.json') *> (Join-Path $bankJob 'banking_compare.log')
    if($LASTEXITCODE) {throw 'Actual tree bank/II post-check failed'}
    $bankState.State='SUCCEEDED';$bankState.Stage='HLS_BANKING_GATES_COMPLETE'
} catch {$bankState.State='FAILED';$bankState['Error']=$_.Exception.Message;throw}
finally {$bankState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-BankingState}
