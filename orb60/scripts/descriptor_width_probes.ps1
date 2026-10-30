[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineDescriptor,[string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$widthShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$widthPrior=Get-Content -LiteralPath (Join-Path $BaselineDescriptor 'status.json') -Raw | ConvertFrom-Json
if($widthPrior.State -ne 'SUCCEEDED' -or !$widthPrior.Cosim -or $widthPrior.Kernel -ne 'descriptor' -or $widthPrior.PeriodNs -ne 10) {throw 'Requires exact accepted baseline descriptor'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_descriptor_width_probes_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$widthJob=[IO.Path]::GetFullPath($Job)
$widthInputs=Join-Path $widthJob 'inputs';New-Item -ItemType Directory -Path $widthInputs -Force | Out-Null
foreach($name in @('descriptor_width_probes.ps1','hls.ps1','hls.tcl','prove_descriptor_widths.py','compare_descriptor_width_probes.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $widthInputs
}
Copy-Item -LiteralPath (Join-Path $Orb60Root 'docs/NEXT_OPTIMIZATION_PLAN_ZH.md') -Destination (Join-Path $widthInputs 'plan_snapshot.md')
$widthManifest=Get-ChildItem -LiteralPath $widthInputs -File | ForEach-Object {
    [ordered]@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$widthManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $widthJob 'tool_manifest.json') -Encoding UTF8
$widthState=[ordered]@{State='RUNNING';Stage='RANGE_PROOF';Job=$widthJob;ProcessId=$PID;BaselineDescriptor=$BaselineDescriptor;
    Scope='Directional exact-CSim and HLS resource/II probes; no repeated baseline run, RTL/protocol/frame/route pending';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-WidthState {$widthState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $widthJob 'status.json') -Encoding UTF8}
Save-WidthState;Write-Output "ORB60_DESCRIPTOR_WIDTH_JOB=$widthJob PID=$PID"
try {
    $widthTables=Join-Path $BaselineDescriptor 'inputs/FPGA_ORB_HLS/fastv2/next/include/backend_tables.h'
    & $ProjectPython (Join-Path $widthInputs 'prove_descriptor_widths.py') --source $widthTables --output (Join-Path $widthJob 'range_proof.json') *> (Join-Path $widthJob 'range_proof.log')
    if($LASTEXITCODE) {throw 'Full integer range proof failed'}
    foreach($mode in @(1,2)) {
        $widthState.Stage="CSIM_SYNTH_MODE$mode";Save-WidthState
        $childFile=Join-Path $widthJob "mode${mode}_job.txt"
        & $widthShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -Period 10 -DescriptorVectors (Join-Path $BaselineDescriptor 'descriptor_vectors') -DescriptorWidthMode $mode -NoExport -JobFile $childFile *> (Join-Path $widthJob "mode${mode}.log")
        if($LASTEXITCODE) {throw "Width mode$mode exact CSim/synthesis failed"}
        $widthState["Mode${mode}HlsJob"]=(Get-Content -LiteralPath $childFile -Raw).Trim();Save-WidthState
    }
    $widthState.Stage='COMPARE';Save-WidthState
    & $ProjectPython (Join-Path $widthInputs 'compare_descriptor_width_probes.py') --baseline $BaselineDescriptor --moment $widthState.Mode1HlsJob --cordic $widthState.Mode2HlsJob --output (Join-Path $widthJob 'comparison.json') *> (Join-Path $widthJob 'compare.log')
    if($LASTEXITCODE) {throw 'Directional width II/interface post-check failed'}
    $widthState.State='SUCCEEDED';$widthState.Stage='WIDTH_PROBES_COMPLETE'
} catch {$widthState.State='FAILED';$widthState['Error']=$_.Exception.Message;throw}
finally {$widthState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-WidthState}
