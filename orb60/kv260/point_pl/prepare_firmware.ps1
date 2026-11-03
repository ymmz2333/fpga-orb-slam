param([Parameter(Mandatory=$true)][string]$Job,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$jobPath=(Resolve-Path -LiteralPath $Job).Path
$outPath=[System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Output))
& $ProjectPython -m orb60.kv260.point_pl.prepare_firmware --job $jobPath --output $outPath
if($LASTEXITCODE -ne 0){throw 'Input preparation failed'}
Push-Location -LiteralPath $outPath
try {
    & (Join-Path $VivadoRoot 'bin/bootgen.bat') -arch zynqmp -image firmware.bif -process_bitstream bin 2>&1 | Out-File -LiteralPath 'bootgen.log' -Encoding utf8
    if($LASTEXITCODE -ne 0){throw 'bootgen failed'}
    # Windows PowerShell treats any native stderr as an ErrorRecord. Preserve
    # DTC warnings in logs and decide success from its actual exit code.
    $ErrorActionPreference='Continue'
    & wsl.exe --cd $outPath -e dtc -@ -I dts -O dtb -o kv260_dpu_points.dtbo kv260_dpu_points.dts 2>&1 | Out-File -LiteralPath 'dtc.log' -Encoding utf8
    $dtExit=$LASTEXITCODE
    & wsl.exe --cd $outPath -e dtc -I dtb -O dts -o overlay_roundtrip.dts kv260_dpu_points.dtbo 2>&1 | Out-File -LiteralPath 'dtc_roundtrip.log' -Encoding utf8
    $roundtripExit=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if($dtExit -ne 0 -or $roundtripExit -ne 0){throw 'DT compilation/roundtrip failed; see logs'}
} finally {Pop-Location}
& $ProjectPython -m orb60.kv260.point_pl.prepare_firmware --output $outPath --finalize
if($LASTEXITCODE -ne 0){throw 'Firmware verification failed'}
