param([Parameter(Mandatory=$true)][string]$Job,
      [ValidateSet('build','reports')][string]$Mode='build')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$env:KV260_UNIFIED_JOB=Join-Path $ProjectRoot $Job
$env:KV260_UNIFIED_MODE=$Mode
if ($Mode -eq 'build') {
    if (Test-Path -LiteralPath $env:KV260_UNIFIED_JOB) { throw 'Choose a new unified job directory' }
    New-Item -ItemType Directory -Path $env:KV260_UNIFIED_JOB | Out-Null
}
$env:KV260_VIVADO_SCRATCH=$VivadoBuildRoot
$sourceDir=Join-Path $env:KV260_UNIFIED_JOB ('source_'+$Mode)
New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'unified.tcl') -Destination $sourceDir
Copy-Item -LiteralPath $PSCommandPath -Destination $sourceDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'audit_routed.tcl') -Destination $sourceDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'check_unified.py') -Destination $sourceDir
$log=Join-Path $env:KV260_UNIFIED_JOB ('console_'+$Mode+'.log')
$previousPreference=$ErrorActionPreference
try {
    # Windows PowerShell otherwise terminates on the first native stderr line,
    # hiding the Vivado exit status and truncating the retained error log.
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $sourceDir 'unified.tcl') *> $log
    $vivadoExit=$LASTEXITCODE
} finally { $ErrorActionPreference=$previousPreference }
if ($vivadoExit -ne 0) { throw "KV260 unified $Mode failed (exit $vivadoExit); inspect $log" }
if (-not (Test-Path (Join-Path $env:KV260_UNIFIED_JOB 'routed.dcp'))) { throw 'Full routed checkpoint missing' }
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $sourceDir 'audit_routed.tcl') *> (Join-Path $env:KV260_UNIFIED_JOB 'console_audit.log')
    $auditExit=$LASTEXITCODE
} finally { $ErrorActionPreference=$previousPreference }
if ($auditExit -ne 0) { throw 'Routed checkpoint audit failed' }
& $ProjectPython (Join-Path $PSScriptRoot 'check_unified.py') $env:KV260_UNIFIED_JOB *> (Join-Path $env:KV260_UNIFIED_JOB 'validation_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Complete route exists but static acceptance failed; inspect validation.json' }
Write-Output "Unified routed checkpoint and reports: $env:KV260_UNIFIED_JOB"
