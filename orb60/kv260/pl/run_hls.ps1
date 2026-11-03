param([Parameter(Mandatory=$true)][ValidateSet('layer2','descriptor')][string]$Kernel,
      [Parameter(Mandatory=$true)][string]$Job,
      [double]$Period=6.666667,
      [ValidateSet(2,4)][int]$Ppc=4)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$jobPath=Join-Path $ProjectRoot $Job
& $ProjectPython -m orb60.kv260.pl.prepare_hls --kernel $Kernel --output $jobPath --period $Period --ppc $Ppc
if ($LASTEXITCODE -ne 0) { throw 'KV260 HLS snapshot failed' }
Push-Location $jobPath
try {
    & $VitisHlsBat -f (Join-Path $jobPath 'run.tcl') *> (Join-Path $jobPath 'console.log')
    if ($LASTEXITCODE -ne 0) { throw "KV260 HLS failed; see $jobPath/console.log" }
    if (-not (Test-Path (Join-Path $jobPath 'unit_pass.stamp'))) { throw 'Missing unit acceptance stamp' }
} finally { Pop-Location }
