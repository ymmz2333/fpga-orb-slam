# Relocatable standalone bundle environment. Machine overrides are local only.
$ErrorActionPreference='Stop'
$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$localConfig=Join-Path $PSScriptRoot 'local_env.ps1'
if(Test-Path -LiteralPath $localConfig){. $localConfig}
function Find-BundleTool([string]$RootSetting,[string]$CommandName){
    $setting=[Environment]::GetEnvironmentVariable($RootSetting,'Process')
    if($setting){return (Join-Path $setting ('bin\'+$CommandName))}
    $command=Get-Command $CommandName -ErrorAction SilentlyContinue
    if($command){return $command.Source}
    return $null
}
$VivadoBat=Find-BundleTool 'FPGA_VIVADO_ROOT' 'vivado.bat'
$VitisHlsBat=Find-BundleTool 'FPGA_VITIS_HLS_ROOT' 'vitis_hls.bat'
$env:FPGA_PROJECT_ROOT=$ProjectRoot
