param(
    [switch]$Live,
    [string]$DroneIP = '192.168.50.24',
    [string]$ExpectedMac = '70:74:14:a4:5d:1c',
    [string]$LabPrefix = '192.168.50.',
    [ValidateRange(0,3)][int]$ControllerIndex = 0,
    [ValidateRange(1,100)][int]$RcLimit = 30,
    [ValidateSet(-1,1)][int]$RollSign = 1,
    [ValidateSet(-1,1)][int]$PitchSign = 1,
    [ValidateSet(-1,1)][int]$VerticalSign = 1,
    [ValidateSet(-1,1)][int]$YawSign = 1,
    [ValidateRange(1,14)][double]$TakeoffTimeout = 12,
    [ValidateRange(1,3)][double]$XYExpo = 1,
    [ValidateRange(1,10)][double]$CenterStopDelay = 2,
    [switch]$NoCenterBrake,
    [ValidateSet('flight','handheld')][string]$CaptureKind = 'flight',
    [ValidateRange(0,5)][int]$Bitrate = 4,
    [ValidateSet('software','d3d11va')][string]$Decoder = 'software',
    [double]$Seconds = 0,
    [switch]$Headless,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')
if ($SelfTest) {
    & $ProjectPython -m unittest discover -s $PSScriptRoot -p test_tt_controller.py -v
    exit $LASTEXITCODE
}
if ($Live -and $Headless) { throw 'Headless is a read-only DRY RUN option, never live flight.' }
$stationArgs = @(
    (Join-Path $PSScriptRoot 'tt_xbox_station.py'),
    '--controller-index', $ControllerIndex, '--rc-limit', $RcLimit,
    '--signs', $RollSign, $PitchSign, $VerticalSign, $YawSign, '--seconds', $Seconds,
    '--takeoff-timeout', $TakeoffTimeout, '--xy-expo', $XYExpo, '--capture-kind', $CaptureKind,
    '--bitrate', $Bitrate, '--decoder', $Decoder, '--center-stop-delay', $CenterStopDelay
)
if ($NoCenterBrake) { $stationArgs += '--no-center-brake' }
if ($Headless) { $stationArgs += '--headless' }
if ($Live) {
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress.StartsWith($LabPrefix) -and $_.AddressState -eq 'Preferred'
    })
    if ($addresses.Count -ne 1) {
        throw 'Exactly one lab IPv4 address is required. Connect PC to the lab router.'
    }
    $address = $addresses[0]
    if (-not $DroneIP) {
        $peers = @(Get-NetNeighbor -InterfaceIndex $address.InterfaceIndex -AddressFamily IPv4 |
            Where-Object {
                $_.LinkLayerAddress -eq $ExpectedMac.Replace(':','-') -and
                $_.IPAddress.StartsWith($LabPrefix)
            })
        if ($peers.Count -ne 1) { throw 'Supply -DroneIP with the current TT router address.' }
        $DroneIP = $peers[0].IPAddress
    }
    $stationArgs += @('--live', '--local-ip', $address.IPAddress, '--drone-ip', $DroneIP,
        '--interface', $address.InterfaceIndex, '--expected-mac', $ExpectedMac)
    Write-Output 'TT SDK controls: start on the ground. LT+RT for 1s takes off; no preflight U required.'
    Write-Output 'Close other TT viewers/apps first. No automatic takeoff. H hover / L land.'
    Write-Output "Takeoff needs 3/5 distinct OK replies within $TakeoffTimeout s, otherwise requests land."
    Write-Output "XY response exponent: $XYExpo. Center stop enabled: $(-not $NoCenterBrake)."
    Write-Output "Center stop: zero RC immediately; one stop after all axes center for $CenterStopDelay s. H stop is immediate. No reply wait."
    Write-Output "Xbox Y / keyboard R: start/stop $CaptureKind video recording. MP4 export runs after stopping."
} else {
    Write-Output 'DRY RUN: no drone network access. Test sticks and button combinations here first.'
}
& $ProjectPython @stationArgs
exit $LASTEXITCODE
