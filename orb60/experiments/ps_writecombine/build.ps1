[CmdletBinding()]
param([string]$KernelBuild='', [string]$Output='', [string]$Distro='Ubuntu-20.04')
. (Join-Path $PSScriptRoot '../../scripts/environment.ps1')
if(!$Output) {$Output=Join-Path $Orb60Root ('build/linux/writecombine_{0}' -f (Get-Date -Format yyyyMMdd_HHmmss))}
$outputPath=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $outputPath) {throw 'Refusing to overwrite existing experiment output'}
$linuxSource=(& wsl.exe -d $Distro --exec wslpath -u $PSScriptRoot).Trim()
if($LASTEXITCODE) {throw 'WSL path conversion failed'}
$linuxOutput=(& wsl.exe -d $Distro --exec wslpath -u $outputPath).Trim()
if($LASTEXITCODE) {throw 'WSL output conversion failed'}
& wsl.exe -d $Distro --exec bash "$linuxSource/build.sh" $linuxOutput $KernelBuild
if($LASTEXITCODE) {throw 'Write-combine experiment build failed'}
Write-Output "ORB60_WC_EXPERIMENT=$outputPath"
