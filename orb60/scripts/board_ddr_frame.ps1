[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FrameJob,
      [ValidateRange(0,8000)][decimal]$EffectiveDdrMBps=0,[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$boardName='{0}_board_ddr_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$boardJob=Join-Path $Orb60Root "build/optimized/gates/$boardName"
$boardTests=Join-Path $boardJob 'inputs/tests'
New-Item -ItemType Directory -Path $boardTests -Force | Out-Null
if($JobFile) {$boardJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
foreach($boardFile in @('prepare_native_frame.py','native_profile.py','run_board_ddr_frame.py',
                        'native_frame.cpp','ddr_time.hpp','check_native_harness.py','native_ddr_model_test.cpp')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "tests/$boardFile") -Destination $boardTests
}
Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/ps_config.tcl') -Destination (Join-Path $boardJob 'inputs/ps_config.tcl')
$boardHashes=Get-ChildItem -LiteralPath (Join-Path $boardJob 'inputs') -Recurse -File | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($boardJob.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$boardHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $boardJob 'test_manifest.json') -Encoding UTF8
Write-Output "ORB60_BOARD_DDR_JOB=$boardJob PID=$PID"
$boardRate=$EffectiveDdrMBps.ToString([Globalization.CultureInfo]::InvariantCulture)
$ErrorActionPreference='Continue'
& $ProjectPython (Join-Path $boardTests 'run_board_ddr_frame.py') --frame-job $FrameJob --output $boardJob `
    --parent-pid $PID --effective-ddr-mbps $boardRate 2>&1 | Tee-Object -FilePath (Join-Path $boardJob 'board_ddr.log')
$boardCode=$LASTEXITCODE;$ErrorActionPreference='Stop'
if($boardCode) {throw "Board DDR capacity simulation failed (exit $boardCode)"}
