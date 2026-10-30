[CmdletBinding()]
param([string]$PairJob='', [string]$Output='', [string]$Distro='Ubuntu-20.04')
. (Join-Path $PSScriptRoot 'environment.ps1')
if(!$PairJob) {
    $parent=(Get-Content -LiteralPath (Join-Path $Orb60Root 'build/optimized/tree_read150_current.txt') -Raw).Trim()
    $prior=Get-Content -LiteralPath (Join-Path $parent 'status.json') -Raw | ConvertFrom-Json
    if($prior.State -ne 'SUCCEEDED') {throw 'Current150MHz release is not accepted'}
    $PairJob=$prior.PairJob
}
if(!$Output) {$Output=Join-Path $Orb60Root ('build/linux/{0}_{1}' -f (Get-Date -Format yyyyMMdd_HHmmss),[guid]::NewGuid().ToString('N').Substring(0,8))}
$outputPath=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $outputPath) {throw 'Refusing to overwrite an existing build'}
& $ProjectPython (Join-Path $PSScriptRoot 'prepare_linux.py') --pair $PairJob --output $outputPath
if($LASTEXITCODE) {throw 'Accepted register/bit pairing failed'}
$linuxRoot=& wsl.exe -d $Distro --exec wslpath -u $Orb60Root.Replace('\','/')
if($LASTEXITCODE -or !$linuxRoot) {throw 'WSL workspace path conversion failed'}
$linuxRoot=$linuxRoot.Trim()
$linuxOutput=& wsl.exe -d $Distro --exec wslpath -u $outputPath.Replace('\','/')
if($LASTEXITCODE -or !$linuxOutput) {throw 'WSL output path conversion failed'}
$linuxOutput=$linuxOutput.Trim()
& wsl.exe -d $Distro --exec bash "$linuxRoot/linux/build.sh" $linuxOutput
if($LASTEXITCODE) {throw 'Linux build/unit/protocol gate failed'}
Push-Location $outputPath
try {
    & (Join-Path $VivadoRoot 'bin/bootgen.bat') -image bitstream.bif -arch zynq -process_bitstream bin -w on
    if($LASTEXITCODE) {throw 'Bootgen conversion failed'}
    $binSha=(Get-FileHash -LiteralPath 'orb60_150mhz.bit.bin').Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $outputPath 'firmware.sha256'),"$binSha  orb60_150mhz.bit.bin`n",[Text.Encoding]::ASCII)
} finally {Pop-Location}
Write-Output "ORB60_LINUX_BUILD=$outputPath; BOARD_DEPLOYMENT_NOT_STARTED"
