[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$LayerHlsJob,[Parameter(Mandatory=$true)][string]$DescriptorHlsJob,[string]$JobFile='',[string]$LayerProtocolReuse='',[string]$DescriptorProtocolReuse='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$axiName='{0}_datapath_axi_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$axiJob=Join-Path $Orb60Root "build/optimized/gates/$axiName"
$axiTests=Join-Path $axiJob 'inputs/tests'
New-Item -ItemType Directory -Path $axiTests -Force | Out-Null
foreach($axiFile in @('run_datapath_axi.py','run_axi.py','gpi_runtime.py','test_datapath_axi.py','test_r11_axi.py','axi_ram.py','oracle.py')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "tests/$axiFile") -Destination $axiTests
}
$axiCommon=Join-Path $axiJob 'inputs/common'
New-Item -ItemType Directory -Path $axiCommon -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'tb/common/axi_lite.py') -Destination $axiCommon
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'tb/common/__init__.py') -Destination $axiCommon
$axiScriptInputs=Join-Path $axiJob 'inputs/scripts';New-Item -ItemType Directory -Path $axiScriptInputs -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'reuse_layer_protocol.py') -Destination $axiScriptInputs
$axiHashes=Get-ChildItem -LiteralPath (Join-Path $axiJob 'inputs') -Recurse -File | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($axiJob.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$axiHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $axiJob 'test_manifest.json') -Encoding UTF8
$axiState=[ordered]@{State='RUNNING';Stage='PROTOCOL_SUBSET';Job=$axiJob;LayerHlsJob=$LayerHlsJob;DescriptorHlsJob=$DescriptorHlsJob;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID;Scope='Isolated 4-master cores with random AXI/reset/completion barrier; shared address space, full/native/system/board gates pending'}
$axiState['LayerProtocolReuse']=$LayerProtocolReuse
$axiState['DescriptorProtocolReuse']=$DescriptorProtocolReuse
$axiStatus=Join-Path $axiJob 'status.json'
$axiState | ConvertTo-Json | Set-Content -LiteralPath $axiStatus -Encoding UTF8
if($JobFile) {$axiJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
Write-Output "ORB60_DATAPATH_AXI_JOB=$axiJob PID=$PID"
try {
    if($DescriptorProtocolReuse) {
        & $ProjectPython (Join-Path $axiScriptInputs 'reuse_layer_protocol.py') --previous $DescriptorProtocolReuse --current $axiJob --layer $DescriptorHlsJob --kernel descriptor *> (Join-Path $axiJob 'descriptor_reuse.log')
        if($LASTEXITCODE) {throw 'Unchanged descriptor protocol reuse verification failed'}
        $axiState.Scope='Fresh layer random AXI/reset/barrier plus verified identical retained descriptor protocol; joint DDR/native/system/board pending'
    }
    if($LayerProtocolReuse) {
        & $ProjectPython (Join-Path $axiScriptInputs 'reuse_layer_protocol.py') --previous $LayerProtocolReuse --current $axiJob --layer $LayerHlsJob *> (Join-Path $axiJob 'layer_reuse.log')
        if($LASTEXITCODE) {throw 'Unchanged layer protocol reuse verification failed'}
        $axiState.Scope='Fresh descriptor random AXI/reset/barrier plus verified identical retained layer protocol evidence; joint DDR/native/system/board gates pending'
    }
    foreach($axiKernel in @('descriptor','layer2')) {
        if($axiKernel -eq 'descriptor' -and $DescriptorProtocolReuse) {continue}
        if($axiKernel -eq 'layer2' -and $LayerProtocolReuse) {continue}
        $axiState.Stage="AXI_$axiKernel";$axiState | ConvertTo-Json | Set-Content -LiteralPath $axiStatus -Encoding UTF8
        if($axiKernel -eq 'descriptor') {
            $axiHls=$DescriptorHlsJob;$axiVectors=Join-Path $axiHls 'descriptor_vectors';$axiCases='35,30,24,25,36,37';$axiResetCase=7
        } else {
            $axiHls=$LayerHlsJob;$axiVectors=Join-Path $axiHls 'oracle_vectors';$axiCases='7,1,14';$axiResetCase=14
        }
        $ErrorActionPreference='Continue'
        & $ProjectPython (Join-Path $axiTests 'run_datapath_axi.py') --hls-job $axiHls --vectors $axiVectors --kernel $axiKernel --cases $axiCases --reset-case $axiResetCase --output (Join-Path $axiJob $axiKernel) 2>&1 | Tee-Object -FilePath (Join-Path $axiJob "$axiKernel.log")
        $axiCode=$LASTEXITCODE;$ErrorActionPreference='Stop'
        if($axiCode) {throw "$axiKernel randomized AXI gate failed (exit $axiCode)"}
    }
    $axiState.State='SUCCEEDED';$axiState.Stage='COMPLETE'
} catch {$axiState.State='FAILED';$axiState['Error']=$_.Exception.Message;throw}
finally {$axiState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$axiState | ConvertTo-Json | Set-Content -LiteralPath $axiStatus -Encoding UTF8}
