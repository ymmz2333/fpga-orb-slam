param(
    [switch]$RequireAmd,
    [switch]$RequireModelSim
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')

$checks = @(
    [pscustomobject]@{Name='Project root'; Path=$ProjectRoot; Required=$true},
    [pscustomobject]@{Name='Python venv'; Path=$ProjectPython; Required=$true},
    [pscustomobject]@{Name='Icarus'; Path=(Join-Path $IcarusBin 'iverilog.exe'); Required=$true},
    [pscustomobject]@{Name='Verilator'; Path=(Join-Path $IcarusBin 'verilator.cmd'); Required=$true},
    [pscustomobject]@{Name='GTKWave'; Path=(Join-Path $GtkWaveBin 'gtkwave.exe'); Required=$false},
    [pscustomobject]@{Name='Vivado 2024.2'; Path=$VivadoBat; Required=$RequireAmd.IsPresent},
    [pscustomobject]@{Name='Vitis 2024.2'; Path=$VitisBat; Required=$RequireAmd.IsPresent},
    [pscustomobject]@{Name='Vitis HLS 2024.2'; Path=$VitisHlsBat; Required=$RequireAmd.IsPresent},
    [pscustomobject]@{Name='Vitis Vision headers'; Path=(Join-Path $VitisVisionRoot 'L1\include'); Required=$RequireAmd.IsPresent},
    [pscustomobject]@{Name='ModelSim/Questa'; Path=(Join-Path $ModelSimBin 'vsim.exe'); Required=$RequireModelSim.IsPresent},
    [pscustomobject]@{Name='ModelSim license'; Path=$ModelSimLicense; Required=$RequireModelSim.IsPresent},
    [pscustomobject]@{Name='Workflow contract'; Path=(Join-Path $ProjectRoot 'panorama\WORKFLOW.md'); Required=$true}
)

$yosysCommand = Get-Command yosys -ErrorAction SilentlyContinue
$checks += [pscustomobject]@{
    Name='Yosys'
    Path=if ($yosysCommand) { $yosysCommand.Source } else { 'not on PATH' }
    Required=$false
}

$failed = @()
$rows = foreach ($check in $checks) {
    $present = Test-Path -LiteralPath $check.Path
    if ($check.Required -and -not $present) { $failed += $check }
    [pscustomobject]@{
        Tool = $check.Name
        Status = if ($present) { 'OK' } elseif ($check.Required) { 'MISSING' } else { 'optional' }
        Path = $check.Path
    }
}

$rows | Format-Table -AutoSize
Write-Output "VIVADO_SCRATCH=$VivadoBuildRoot"
if (Test-Path -LiteralPath $ProjectPython) {
    $pythonVersion = (& $ProjectPython -c 'import platform; print(platform.python_version())').Trim()
    Write-Output "PYTHON_VERSION=$pythonVersion"
    if ($pythonVersion -ne '3.12.12') {
        throw "Project Python must be 3.12.12, found $pythonVersion"
    }
}
if ($failed.Count -ne 0) {
    throw ('Required environment checks failed: ' + (($failed.Name) -join ', '))
}
Write-Output 'ENVIRONMENT_CHECK=PASSED'
