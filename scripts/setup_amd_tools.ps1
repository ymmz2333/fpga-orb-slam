param(
    [switch]$PrintOnly
)

. (Join-Path $PSScriptRoot 'project_env.ps1')

foreach ($required in @(
    $VivadoBat,
    $VitisBat,
    $VitisHlsBat,
    (Join-Path $VitisVisionRoot 'L1\include')
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required AMD tool path is missing: $required"
    }
}

if ($PrintOnly) {
    Write-Host "Project root    : $ProjectRoot"
    Write-Host "Vivado          : $VivadoBat"
    Write-Host "Vitis           : $VitisBat"
    Write-Host "Vitis HLS       : $VitisHlsBat"
    Write-Host "Vitis Vision    : $VitisVisionRoot"
    Write-Host "Vivado scratch  : $VivadoBuildRoot"
} else {
    Write-Host 'AMD 2024.2 tools are available in this PowerShell process.'
    Write-Host 'Use dot-sourcing so the environment remains active:'
    Write-Host '  . .\scripts\setup_amd_tools.ps1'
}
