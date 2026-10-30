param(
    [string]$DroneIP = '192.168.50.24',
    [string]$ExpectedMac = '70:74:14:a4:5d:1c',
    [string]$LabPrefix = '192.168.50.',
    [ValidateSet('flight','handheld')][string]$CaptureKind = 'handheld',
    [ValidateRange(0,5)][int]$Bitrate = 4,
    [ValidateSet('software','d3d11va')][string]$Decoder = 'software',
    [switch]$CompareRK,
    [ValidateSet('jpegenc','mppjpegenc-copy')][string]$RKPreviewEncoder = 'jpegenc',
    [switch]$AutoRecord,
    [ValidateRange(0,3)][int]$ControllerIndex = 0,
    [double]$Seconds = 0,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')
$viewer = Join-Path $PSScriptRoot 'tt_video_viewer.py'
if ($SelfTest) {
    & $ProjectPython $viewer --self-test
    exit $LASTEXITCODE
}
$addresses = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress.StartsWith($LabPrefix) -and $_.AddressState -eq 'Preferred'
})
if ($addresses.Count -ne 1) {
    throw 'Connect the PC to the lab router first. Exactly one lab IPv4 address is required.'
}
$address = $addresses[0]
if (-not $DroneIP) {
    $macKey = $ExpectedMac.Replace(':','-')
    $peers = @(Get-NetNeighbor -InterfaceIndex $address.InterfaceIndex -AddressFamily IPv4 |
        Where-Object { $_.LinkLayerAddress -eq $macKey -and $_.IPAddress.StartsWith($LabPrefix) })
    if ($peers.Count -ne 1) {
        throw 'No unique known TT neighbor. Supply -DroneIP with its current router client-list address.'
    }
    $DroneIP = $peers[0].IPAddress
}
Write-Output "TT video-only viewer: $($address.IPAddress) -> $DroneIP, interface $($address.InterfaceIndex)"
Write-Output "R: start/stop $CaptureKind video. SPACE: 10s latency test. Esc/Q: close. S: image. No flight controls."
$recordArgs = @()
if ($AutoRecord) { $recordArgs += '--auto-record' }
& $ProjectPython $viewer --local-ip $address.IPAddress --drone-ip $DroneIP `
    --interface $address.InterfaceIndex --expected-mac $ExpectedMac --seconds $Seconds --capture-kind $CaptureKind `
    --bitrate $Bitrate --decoder $Decoder --compare-rk ([int]$CompareRK.IsPresent) --rk-preview-encoder $RKPreviewEncoder --controller-index $ControllerIndex @recordArgs
exit $LASTEXITCODE
