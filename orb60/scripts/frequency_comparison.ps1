[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Job,
      [ValidateSet('Layer4','Layer2','Descriptor','Route4','Route2')][string]$Mode)
. (Join-Path $PSScriptRoot 'environment.ps1')
$freqJob=[IO.Path]::GetFullPath($Job)
$freqConfig=Get-Content -LiteralPath (Join-Path $freqJob 'status.json') -Raw | ConvertFrom-Json
$freqShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$freqModeFile=Join-Path $freqJob ($Mode.ToLowerInvariant()+'_status.json')
$freqState=[ordered]@{State='RUNNING';Stage=$Mode;ProcessId=$PID;StartedUtc=[DateTime]::UtcNow.ToString('o');Scope='Fresh8ns HLS and bounded125MHz routed comparison; no inherited frame or board performance'}
function Save-FrequencyMode {$freqState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $freqModeFile -Encoding UTF8}
Save-FrequencyMode
try {
    if($Mode -in @('Layer4','Layer2','Descriptor')) {
        $hlsPointer=Join-Path $freqJob ($Mode.ToLowerInvariant()+'_hls_job.txt')
        $hlsArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'hls.ps1'),'-Variant','optimized','-Period','8','-Cosim','-JobFile',$hlsPointer)
        if($Mode -eq 'Descriptor') {
            $hlsArgs+=@('-Kernel','descriptor','-DescriptorWidthMode','2','-DescriptorPrefetch','8','-DescriptorPatch32','-SourceJob',$freqConfig.DescriptorSource,'-DescriptorVectors',(Join-Path $freqConfig.DescriptorSource 'descriptor_vectors'))
        } elseif($Mode -eq 'Layer4') {
            $hlsArgs+=@('-Kernel','layer2','-LayerPpc','4','-FastStaged','-LayerIoOverlap','-LayerBramFifos','-SourceJob',$freqConfig.LayerSource)
        } else {
            $hlsArgs+=@('-Kernel','layer2','-LayerPpc','2','-FastStaged')
        }
        & $freqShell @hlsArgs *> (Join-Path $freqJob ($Mode.ToLowerInvariant()+'_hls.log'))
        if($LASTEXITCODE) {throw 'Fresh8ns exact HLS failed; retain frozen failure evidence'}
        $hls=(Get-Content -LiteralPath $hlsPointer -Raw).Trim()
        $accepted=Join-Path $freqJob ('accepted_'+$Mode.ToLowerInvariant())
        New-Item -ItemType Directory -Path $accepted -Force | Out-Null
        $compareArgs=@('--job',$hls,'--output',(Join-Path $accepted 'comparison.json'))
        $checker=if($Mode -eq 'Descriptor') {'compare_descriptor.py'} else {'compare_layer2.py'}
        if($Mode -ne 'Descriptor') {$compareArgs+=@('--front2',$freqConfig.FrontReference)}
        & $ProjectPython (Join-Path $PSScriptRoot $checker) @compareArgs *> (Join-Path $freqJob ($Mode.ToLowerInvariant()+'_compare.log'))
        if($LASTEXITCODE) {throw 'Fresh8ns pipeline/interface acceptance failed'}
        $acceptedState=[ordered]@{State='SUCCEEDED';HlsJob=$hls;PeriodNs=8;Scope='Fresh exact C/RTL plus II/interface gates only'}
        $acceptedState[$(if($Mode -eq 'Descriptor') {'DescriptorHlsJob'} else {'layer2Job'})]=$hls
        $acceptedState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $accepted 'status.json') -Encoding UTF8
        $freqState['HlsJob']=$hls
    } else {
        $layerMode=if($Mode -eq 'Route4') {'layer4'} else {'layer2'}
        & $freqShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') -AcceptedLayer (Join-Path $freqJob ('accepted_'+$layerMode)) -AcceptedDescriptor (Join-Path $freqJob 'accepted_descriptor') -FrequencyMHz 125 -Jobs 4 -ExtendedDiagnostics -JobFile (Join-Path $freqJob ($Mode.ToLowerInvariant()+'_job.txt')) *> (Join-Path $freqJob ($Mode.ToLowerInvariant()+'.log'))
        if($LASTEXITCODE) {throw 'Fresh125MHz complete routed comparison failed; retain actual timing evidence'}
        $route=(Get-Content -LiteralPath (Join-Path $freqJob ($Mode.ToLowerInvariant()+'_job.txt')) -Raw).Trim()
        $proof=Get-Content -LiteralPath (Join-Path $route 'status.json') -Raw | ConvertFrom-Json
        if($proof.State -ne 'SUCCEEDED') {throw 'Missing fresh125MHz routed acceptance'}
        $freqState['RouteJob']=$route;$freqState['Timing']=$proof.Timing
    }
    $freqState.State='SUCCEEDED';$freqState.Stage='COMPLETE'
} catch {$freqState.State='FAILED';$freqState['Error']=$_.Exception.Message;throw}
finally {$freqState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-FrequencyMode}
