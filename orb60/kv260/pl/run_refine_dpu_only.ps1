param([Parameter(Mandatory=$true)][string]$BaseJob,
      [Parameter(Mandatory=$true)][string]$Job)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$env:KV260_DPU_ONLY_JOB=Join-Path $ProjectRoot $Job
$env:KV260_DPU_ONLY_BASE=Join-Path $ProjectRoot $BaseJob
$jobPath=$env:KV260_DPU_ONLY_JOB
if (Test-Path -LiteralPath $jobPath) { throw 'Choose a new refinement job directory' }
if (-not (Test-Path (Join-Path $env:KV260_DPU_ONLY_BASE 'routed.dcp'))) { throw 'Full routed base checkpoint missing' }
New-Item -ItemType Directory -Path $jobPath | Out-Null
foreach ($name in @('build_config.json','dpu_arch.json','dpu_properties.tsv','bd_inventory.tsv','address_map.tsv','system_generated.tcl','project_path.txt','synthesized_utilization.rpt','synthesized_hierarchy.rpt')) {
    Copy-Item -LiteralPath (Join-Path $env:KV260_DPU_ONLY_BASE $name) -Destination $jobPath
}
@{base_job=$BaseJob;target_job=$Job;operation='phys_opt_design -directive AggressiveExplore; conditional route_design -tns_cleanup';
  base_checkpoint_sha256=(Get-FileHash (Join-Path $env:KV260_DPU_ONLY_BASE 'routed.dcp') -Algorithm SHA256).Hash.ToLower();
  constraints_changed=$false;clocks_changed=$false;started_utc=[DateTime]::UtcNow.ToString('o')} |
  ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $jobPath 'refinement.json')
$sourceDir=Join-Path $jobPath 'source_build'
New-Item -ItemType Directory -Path $sourceDir | Out-Null
foreach ($name in @('refine_dpu_only.tcl','report_dpu_only.tcl','export_dpu_only.tcl','check_dpu_only.py','run_refine_dpu_only.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $sourceDir
}
$oldPreference=$ErrorActionPreference
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $sourceDir 'refine_dpu_only.tcl') *> (Join-Path $jobPath 'console_build.log')
    $toolExit=$LASTEXITCODE
} finally { $ErrorActionPreference=$oldPreference }
if ($toolExit -ne 0) { throw 'Post-route refinement failed; original route retained' }
& $ProjectPython (Join-Path $sourceDir 'check_dpu_only.py') $jobPath *> (Join-Path $jobPath 'validation_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Refinement did not pass full static acceptance; no bitstream exported' }
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $sourceDir 'export_dpu_only.tcl') *> (Join-Path $jobPath 'console_export.log')
    $toolExit=$LASTEXITCODE
} finally { $ErrorActionPreference=$oldPreference }
if ($toolExit -ne 0) { throw 'Refined bitstream export failed' }
& $ProjectPython (Join-Path $sourceDir 'check_dpu_only.py') $jobPath --release *> (Join-Path $jobPath 'release_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Refined artifact release check failed' }
Write-Output "Refined DPU-only full static and export gates passed; board untested: $jobPath"
