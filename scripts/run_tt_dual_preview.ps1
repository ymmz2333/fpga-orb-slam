param(
    [ValidateRange(0,5)][int]$Bitrate = 4,
    [ValidateSet('software','d3d11va')][string]$Decoder = 'd3d11va',
    [ValidateSet('jpegenc','mppjpegenc-copy')][string]$RKPreviewEncoder = 'jpegenc',
    [ValidateSet('handheld','flight')][string]$CaptureKind = 'handheld',
    [double]$Seconds = 0,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
# Read-only dual preview. This entry contains no takeoff, RC or motor commands.
& (Join-Path $PSScriptRoot 'run_tt_video_viewer.ps1') -CompareRK -Bitrate $Bitrate `
    -Decoder $Decoder -RKPreviewEncoder $RKPreviewEncoder -CaptureKind $CaptureKind `
    -Seconds $Seconds -SelfTest:$SelfTest
exit $LASTEXITCODE
