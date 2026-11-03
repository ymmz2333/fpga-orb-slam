param([Parameter(Mandatory=$true)][string]$Job)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$env:KV260_ORB_ONLY_JOB=Join-Path $ProjectRoot $Job
if(Test-Path -LiteralPath $env:KV260_ORB_ONLY_JOB){throw 'Fresh ORB-only job required'}
New-Item -ItemType Directory -Path $env:KV260_ORB_ONLY_JOB | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'orb_only.tcl') -Destination $env:KV260_ORB_ONLY_JOB
Copy-Item -LiteralPath $PSCommandPath -Destination $env:KV260_ORB_ONLY_JOB
$oldPreference=$ErrorActionPreference
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $env:KV260_ORB_ONLY_JOB 'orb_only.tcl') *> (Join-Path $env:KV260_ORB_ONLY_JOB 'console.log')
    $result=$LASTEXITCODE
} finally {$ErrorActionPreference=$oldPreference}
if($result -ne 0){throw "ORB-only candidate failed: $result; inspect console.log"}
