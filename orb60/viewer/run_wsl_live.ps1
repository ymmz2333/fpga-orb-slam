param(
    [string]$Distribution = 'Ubuntu-20.04',
    [int]$Frames = 0,
    [int]$Port = 18767,
    [double]$Seconds = 0,
    [ValidateRange(0,250)][int]$BufferMs = 120
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../scripts/project_env.ps1')
$name = 'wsl_live_' + [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fff')
$session = Join-Path $ProjectRoot "orb60/build/viewer/$name"
$parent = Split-Path -Parent $session
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$wslExecutable = Join-Path $env:SystemRoot 'System32/wsl.exe'
$wslRoot = (& $wslExecutable -d $Distribution --exec wslpath -a $ProjectRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not $wslRoot.StartsWith('/')) { throw 'Cannot resolve the workspace in WSL' }
$probe = [System.Net.Sockets.TcpClient]::new()
try { $probe.Connect('127.0.0.1', $Port); throw "Viewer port $Port is already in use; close the previous live viewer first" }
catch [System.Net.Sockets.SocketException] { }
finally { $probe.Dispose() }
$arguments = @('-d', $Distribution, '--exec', 'python3', "$wslRoot/orb60/viewer/wsl_live.py", '--output', "$wslRoot/orb60/build/viewer/$name", '--frames', "$Frames", '--port', "$Port", '--linger')
if ($arguments | Where-Object { $_.Contains('"') }) { throw 'Unsupported quote in WSL arguments' }
$quoted = $arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
$controller = Start-Process -FilePath $wslExecutable -ArgumentList $quoted -WindowStyle Hidden -RedirectStandardOutput "$session.controller.log" -RedirectStandardError "$session.controller.stderr.log" -PassThru
$viewerExit = 0
try {
    $ready = Join-Path $session 'session.json'
    for ($attempt=0; $attempt -lt 150 -and -not (Test-Path -LiteralPath $ready); $attempt++) {
        if ($controller.HasExited) { throw "WSL failed to start; inspect $session.controller.stderr.log" }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-Path -LiteralPath $ready)) { throw 'WSL FPGA connection timeout; check the wired connection and board feature service' }
    $video = Join-Path $ProjectRoot 'recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4'
    $viewerArgs = @((Join-Path $PSScriptRoot 'app.py'), '--connect', "127.0.0.1:$Port", '--frame-map', (Join-Path $session 'source_frames.csv'), '--metrics', (Join-Path $session 'desktop_metrics.json'), '--processor', 'PC / WSL', '--buffer-ms', "$BufferMs")
    if (Test-Path -LiteralPath $video) { $viewerArgs += @('--video', $video) }
    if ($Seconds -gt 0) { $viewerArgs += @('--exit-after', "$Seconds") }
    & $ProjectPython @viewerArgs
    $viewerExit = $LASTEXITCODE
} finally {
    if (Test-Path -LiteralPath $session) { New-Item -ItemType File -Path (Join-Path $session 'stop') -Force | Out-Null }
    if (-not $controller.HasExited) { $null = $controller.WaitForExit(15000) }
}
exit $viewerExit
