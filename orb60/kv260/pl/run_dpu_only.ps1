param([Parameter(Mandatory=$true)][string]$Job,
      [ValidateSet('build','reports','export')][string]$Mode='build',
      [ValidateSet(200,250,300)][int]$DpuMHz=250)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$env:KV260_DPU_ONLY_JOB=Join-Path $ProjectRoot $Job
$env:KV260_DPU_ONLY_MODE=$Mode
$env:KV260_DPU_MHZ=[string]$DpuMHz
$jobPath=$env:KV260_DPU_ONLY_JOB
if ($Mode -eq 'build') {
    if (Test-Path -LiteralPath $jobPath) { throw 'Choose a new DPU-only job directory' }
    & $ProjectPython (Join-Path $PSScriptRoot 'prepare_unified_vendor.py')
    if ($LASTEXITCODE -ne 0) { throw 'Official vendor verification failed' }
    New-Item -ItemType Directory -Path $jobPath | Out-Null
    @{platform_kind='dpu_only';dpu_mhz=$DpuMHz;dsp_mhz=2*$DpuMHz;control_mhz=150;
      started_utc=[DateTime]::UtcNow.ToString('o');board_verified=$false} |
        ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $jobPath 'build_config.json')
} else {
    $cfg=Get-Content (Join-Path $jobPath 'build_config.json') -Raw | ConvertFrom-Json
    $env:KV260_DPU_MHZ=[string]$cfg.dpu_mhz
}
$sourceDir=Join-Path $jobPath ('source_'+$Mode)
if (Test-Path -LiteralPath $sourceDir) { throw "Retained source snapshot already exists: $sourceDir" }
New-Item -ItemType Directory -Path $sourceDir | Out-Null
foreach ($name in @('dpu_only.tcl','report_dpu_only.tcl','export_dpu_only.tcl','check_dpu_only.py','run_dpu_only.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $sourceDir
}
if ($Mode -ne 'export') {
    $oldPreference=$ErrorActionPreference
    try {
        $ErrorActionPreference='Continue'
        & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $sourceDir 'dpu_only.tcl') *> (Join-Path $jobPath ('console_'+$Mode+'.log'))
        $toolExit=$LASTEXITCODE
    } finally { $ErrorActionPreference=$oldPreference }
    if ($toolExit -ne 0) { throw "DPU-only $Mode failed (exit $toolExit). See $jobPath" }
}
& $ProjectPython (Join-Path $sourceDir 'check_dpu_only.py') $jobPath *> (Join-Path $jobPath 'validation_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Full-top static acceptance failed; see validation.json' }
$oldPreference=$ErrorActionPreference
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $sourceDir 'export_dpu_only.tcl') *> (Join-Path $jobPath 'console_export.log')
    $toolExit=$LASTEXITCODE
} finally { $ErrorActionPreference=$oldPreference }
if ($toolExit -ne 0) { throw 'Static gate passed but bitstream export failed' }
& $ProjectPython (Join-Path $sourceDir 'check_dpu_only.py') $jobPath --release *> (Join-Path $jobPath 'release_console.log')
if ($LASTEXITCODE -ne 0) { throw 'Export artifact validation failed' }
Write-Output "DPU-only routed, static checks passed and bitstream exported; board untested: $jobPath"
