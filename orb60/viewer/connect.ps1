param(
    [string]$SshAlias = 'rk3588',
    [int]$LocalPort = 18765,
    [int]$RemotePort = 8765,
    [string]$Video = '',
    [string]$FrameMap = ''
)
$ErrorActionPreference = 'Stop'
# The RK bridge must already listen on loopback. Only this viewer's tunnel is owned here.
$tunnel = $null
$client = [System.Net.Sockets.TcpClient]::new()
try {
    try { $client.Connect('127.0.0.1', $LocalPort) } catch { }
    if (-not $client.Connected) {
        if ($SshAlias -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Invalid SSH alias' }
        if ($LocalPort -lt 1024 -or $LocalPort -gt 65535 -or $RemotePort -lt 1 -or $RemotePort -gt 65535) { throw 'Invalid port' }
        $tunnel = Start-Process -FilePath ssh -ArgumentList @('-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15', '-L', "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}", $SshAlias) -WindowStyle Hidden -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if ($tunnel.HasExited) { throw 'SSH tunnel failed; check key authentication and the RK bridge' }
            $probe = [System.Net.Sockets.TcpClient]::new()
            try { $probe.Connect('127.0.0.1', $LocalPort); $ready = $true } catch { } finally { $probe.Dispose() }
            if ($ready) { break }
            Start-Sleep -Milliseconds 200
        }
        if (-not $ready) { throw 'SSH tunnel timeout' }
    }
    $client.Dispose()
    & (Join-Path $PSScriptRoot 'run.ps1') -Connect "127.0.0.1:$LocalPort" -Video $Video -FrameMap $FrameMap
} finally {
    $client.Dispose()
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id }
}
