# Downloads source references only; never imports SDK code or connects to TT.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')
$sdkCommit = 'ff6646e115ab125af3207a4ed3df42cc76c795b2'
$sdkReference = Join-Path $env:FPGA_PROJECT_ROOT ('.work/tt-sdk-reference/' + $sdkCommit)
New-Item -ItemType Directory -Path $sdkReference -Force | Out-Null
$sdkHashes = @{
    'flight.py' = '7b7a37dd8077a808119c380e7c0ed47d9ea1d026deeebe8e5ee8f7534a5a71eb'
    'action.py' = '2b9ff3f26d4f28fd2b40e376740c4f799b93167c4572ed4a68a36deaf4c1fc39'
}
foreach ($sdkName in $sdkHashes.Keys) {
    $sdkPath = Join-Path $sdkReference $sdkName
    if (-not (Test-Path -LiteralPath $sdkPath)) {
        $sdkUrl = "https://raw.githubusercontent.com/dji-sdk/RoboMaster-SDK/$sdkCommit/src/robomaster/$sdkName"
        Invoke-WebRequest -UseBasicParsing -Uri $sdkUrl -OutFile $sdkPath
    }
    if ((Get-FileHash -LiteralPath $sdkPath -Algorithm SHA256).Hash -ne $sdkHashes[$sdkName]) {
        throw "Official reference hash mismatch; existing file left unchanged: $sdkPath"
    }
    Write-Output "Verified TT SDK reference: $sdkName"
}
Write-Output $sdkReference
