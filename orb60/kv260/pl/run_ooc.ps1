param([Parameter(Mandatory=$true)][ValidateSet('layer2','descriptor')][string]$Kernel,
      [Parameter(Mandatory=$true)][string]$HlsJob,
      [Parameter(Mandatory=$true)][string]$Job)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$env:KV260_HLS_JOB=(Resolve-Path -LiteralPath (Join-Path $ProjectRoot $HlsJob)).Path
$env:KV260_OOC_JOB=Join-Path $ProjectRoot $Job
$env:KV260_OOC_KERNEL=$Kernel
if (Test-Path -LiteralPath $env:KV260_OOC_JOB) { throw 'Choose a new OOC output directory' }
New-Item -ItemType Directory -Path $env:KV260_OOC_JOB | Out-Null
& $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $PSScriptRoot 'ooc_route.tcl') *> (Join-Path $env:KV260_OOC_JOB 'console.log')
if ($LASTEXITCODE -ne 0) { throw "K26 OOC failed: $env:KV260_OOC_JOB/console.log" }
if (-not (Test-Path (Join-Path $env:KV260_OOC_JOB 'status.json'))) { throw 'OOC completion missing' }
