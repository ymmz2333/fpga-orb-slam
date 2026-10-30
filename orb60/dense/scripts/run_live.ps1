param([int]$Frames=0,[int]$Port=18769,[double]$Seconds=0,
    [string]$FpgaHost='[fe80::20a:35ff:fe00:122%eth0]:5600',
    [ValidateSet('app.py','qa_live_controls.py','qa_live_failure.py')][string]$ViewerScript='app.py')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$rk=Join-Path $ProjectRoot 'rk3588/orbslam3_cpu_baseline/scripts/rk.ps1'
$board=Get-Content -Raw (Join-Path $ProjectRoot 'rk3588/orbslam3_cpu_baseline/local_board.json') | ConvertFrom-Json
$alias=$board.sshAlias; $remoteRoot=$board.remoteRoot
if ($alias -notmatch '^[a-zA-Z0-9_.-]+$' -or $remoteRoot -notmatch '^(~/|/)[a-zA-Z0-9_./-]+$') {throw 'Invalid board configuration'}
if ($Port -lt 1024 -or $Port -gt 65535 -or $Frames -lt 0) {throw 'Invalid live session arguments'}
if ($FpgaHost -notmatch '^(\[[a-zA-Z0-9:%._-]+\]|[a-zA-Z0-9._-]+):[0-9]+$') {throw 'Invalid FPGA endpoint'}
. (Join-Path $PSScriptRoot 'live_window.ps1')
$instanceName='Local\ORB60_Dense_'+$Port+'_'+([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToLowerInvariant())))).Replace('-','').Substring(0,16)
$instanceLock=[Threading.Mutex]::new($false,$instanceName);$ownsInstance=$false
try {
try {$ownsInstance=$instanceLock.WaitOne(0)}
catch [Threading.AbandonedMutexException] {$ownsInstance=$true}
$existing=Show-Orb60LiveWindow $ProjectRoot $Port
if ($existing.Found) {
    Write-Host '已切回正在运行的实时窗口。如需从首帧重新处理，请点击窗口中的“重新开始”。'
    exit 0
}
if (-not $ownsInstance) {
    Write-Host '实时上位机正在启动或清理旧任务，请稍等；没有重复启动处理。'
    exit 0
}
$probe=[Net.Sockets.TcpClient]::new()
try {$probe.Connect('127.0.0.1',$Port);throw "端口 $Port 已被其它程序或残留隧道占用，但没有找到本项目窗口。未启动新的 FPGA 任务。"}
catch [Net.Sockets.SocketException] { }
finally {$probe.Dispose()}
$sourceMap='runtime/c/datasets/TT_C1_01/flight_20261004T184929_998838_6bb93c56'
$video=Join-Path $ProjectRoot 'recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4'
if (-not (Test-Path -LiteralPath $video)) {throw 'This live session needs its original paired video'}
& ssh -o BatchMode=yes $alias "test -f $remoteRoot/runtime/dense/live_app/READY"
if ($LASTEXITCODE) {throw '实时处理组件尚未构建验证通过。'}
$modules=@('__init__.py','live.py','live_protocol.py','live_server.py','fpga_guard.py','geometry.py','ply.py') | ForEach-Object {Join-Path $PSScriptRoot "../$_"}
& scp -o BatchMode=yes @modules "${alias}:$remoteRoot/runtime/dense/live_app/dense/"
if ($LASTEXITCODE) {throw 'Cannot synchronize live controller source'}
& scp -o BatchMode=yes (Join-Path $ProjectRoot 'orb60/scripts/run_slam_network.py') (Join-Path $ProjectRoot 'orb60/linux/client.py') (Join-Path $PSScriptRoot 'stop_live.py') "${alias}:$remoteRoot/runtime/dense/live_app/"
if ($LASTEXITCODE) {throw 'Cannot synchronize physical FPGA client and controller'}
$again=$true
function Stop-OwnedSession([string]$Session,[string]$LogPath) {
    $result=& powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec "python3 runtime/dense/live_app/stop_live.py --run $Session" -Name dense-live-stop -Seconds 55
    $result | Set-Content -Encoding UTF8 $LogPath
    if ($LASTEXITCODE -or ($result -join "`n") -notmatch 'status=SUCCEEDED exit_code=0') {
        throw 'Cleanup not acknowledged; restart refused to avoid overlapping FPGA clients.'
    }
}
while ($again) {
    $again=$false
    $name='live_'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fff')
    $local=Join-Path $ProjectRoot "orb60/build/dense/$name"
    New-Item -ItemType Directory -Force $local | Out-Null
    $remote="runtime/dense/live_sessions/$name"
    $control=Join-Path $local 'control.json'
    & scp -o BatchMode=yes "${alias}:$remoteRoot/$sourceMap/frames.csv" (Join-Path $local 'source_frames.csv')
    if ($LASTEXITCODE) {throw 'Cannot obtain source-frame mapping'}
    $command='OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH="$PWD/runtime/dense/live_app" python3 -m dense.live ' +
        "--video runtime/dense/input.mp4 --dataset $sourceMap --camera configs/c/tello_oafd_960x720_provisional.yaml " +
        "--slam-root vendor/ORB_SLAM3 --worker runtime/dense/live_app/npu_build/dense_npu_worker " +
        "--executable runtime/dense/live_app/frontend_build/mono_euroc_live --library-directory runtime/dense/live_app/frontend_build/lib " +
        "--model runtime/dense/midas-small-fp16/depth.rknn --npu-acceptance runtime/dense/midas-small-fp16/acceptance.json " +
        "--network-runner runtime/dense/live_app/run_slam_network.py --fpga-client runtime/dense/live_app/client.py " +
        "--fpga-host '$FpgaHost' --output $remote --frames $Frames --port $Port --linger"
    $response=& powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec $command -Name dense-live -Seconds 1
    $response | Set-Content -Encoding UTF8 (Join-Path $local 'job_start.log')
    if (($response -join "`n") -notmatch 'job_id=([a-zA-Z0-9_-]+)') {throw 'Could not start live processing job'}
    $jobId=$Matches[1]
    @{job_id=$jobId;remote=$remote;port=$Port;semantics='actual FPGA SLAM and NPU incremental preview'} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $local 'session.local.json')
    @{launcher_pid=$PID;directory=$name;mode='actual_incremental_processing'} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $ProjectRoot 'orb60/build/dense/live_launch.local.json')
    $tunnel=$null;$stopped=$false
    try {
        $tunnelArgs=@('-N','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','-L',"127.0.0.1:${Port}:127.0.0.1:${Port}",$alias)
        $tunnel=Start-Process -FilePath 'ssh.exe' -ArgumentList $tunnelArgs -WindowStyle Hidden -RedirectStandardOutput (Join-Path $local 'tunnel.log') -RedirectStandardError (Join-Path $local 'tunnel.stderr.log') -PassThru
        $viewerArgs=@((Join-Path $ProjectRoot "orb60/viewer/$ViewerScript"),'--dense-live',"127.0.0.1:$Port",'--video',$video,
            '--frame-map',(Join-Path $local 'source_frames.csv'),'--metrics',(Join-Path $local 'desktop_metrics.json'),'--control-file',$control)
        if ($Seconds -gt 0) {$viewerArgs+=@('--exit-after',$Seconds.ToString([cultureinfo]::InvariantCulture))}
        if ($ViewerScript -eq 'qa_live_controls.py') {
            $expected=if ($Frames -gt 0) {$Frames} else {2273}
            $viewerArgs+=@('--qa-frames',$expected)
        }
        Write-Host '正在验证 FPGA 实际请求；通过后才启动 SLAM 和 NPU。重新开始会清理旧任务后从首帧重新处理。'
        $quoted=$viewerArgs | ForEach-Object {'"'+$_+'"'}
        $viewerPython=Join-Path (Split-Path $ProjectPython) 'pythonw.exe'
        if (-not (Test-Path -LiteralPath $viewerPython)) {$viewerPython=$ProjectPython}
        $viewer=Start-Process -FilePath $viewerPython -ArgumentList $quoted -WindowStyle Normal -RedirectStandardOutput (Join-Path $local 'viewer.log') -RedirectStandardError (Join-Path $local 'viewer.stderr.log') -PassThru
        while (-not $viewer.HasExited) {
            if ((Test-Path -LiteralPath $control) -and -not $stopped) {
                $request=Get-Content -Raw $control | ConvertFrom-Json
                if ($request.action -eq 'stop') {
                    Stop-OwnedSession $remote (Join-Path $local 'stop.log')
                    $stopped=$true
                }
            }
            Start-Sleep -Milliseconds 200;$viewer.Refresh()
        }
        $viewer.WaitForExit();$viewerExit=$viewer.ExitCode
        if (Test-Path -LiteralPath $control) {$again=(Get-Content -Raw $control | ConvertFrom-Json).action -eq 'restart'}
    } finally {
        if (-not $stopped) {
            Stop-OwnedSession $remote (Join-Path $local 'stop.log')
        }
        if ($tunnel -and -not $tunnel.HasExited) {Stop-Process -Id $tunnel.Id}
    }
}
exit $viewerExit
} finally {
    if ($ownsInstance) {$instanceLock.ReleaseMutex()}
    $instanceLock.Dispose()
}
