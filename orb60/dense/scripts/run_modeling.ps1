param([Parameter(Mandatory=$true)][string]$Video,
      [string]$Camera,[switch]$ApproximateCamera,
      [string]$Name = ('video_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
      [string]$FpgaHost = '[fe80::20a:35ff:fe00:122%eth0]:5600',
      [ValidateRange(0,60)][int]$Seconds = 30)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
if ($Name -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Name must contain only letters, digits, underscores or hyphens' }
if (-not $Camera -and -not $ApproximateCamera) { throw 'Provide -Camera or explicitly choose -ApproximateCamera' }
if ($FpgaHost -notmatch '^\[[a-fA-F0-9:%a-zA-Z_.-]+\]:[0-9]+$|^[a-zA-Z0-9_.-]+:[0-9]+$') { throw 'Invalid FPGA endpoint' }
$boardRoot = Join-Path $ProjectRoot 'rk3588/orbslam3_cpu_baseline'
$rk = Join-Path $boardRoot 'scripts/rk.ps1'
$board = Get-Content -Raw (Join-Path $boardRoot 'local_board.json') | ConvertFrom-Json
$alias = $board.sshAlias; $remoteRoot = $board.remoteRoot
if ($alias -notmatch '^[a-zA-Z0-9_.-]+$' -or $remoteRoot -notmatch '^(~/|/)[a-zA-Z0-9_./-]+$') { throw 'Invalid board settings' }
$local = Join-Path $ProjectRoot "orb60/build/dense/jobs/$Name"
New-Item -ItemType Directory -Force $local | Out-Null
$record = Join-Path $local 'job.local.json'
if (Test-Path $record) {
    $prior = Get-Content -Raw $record | ConvertFrom-Json
    $status = & powershell -NoProfile -ExecutionPolicy Bypass -File $rk status $prior.job_id
    $status | Write-Output
    if (($status -join "`n") -match 'status=(STARTING|RUNNING)') { return }
}
$remote = "runtime/dense/jobs/$Name"
$command = "mkdir -p $remote/inputs runtime/dense/app/dense/scripts"
$setup = & powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec $command -Name dense-input-dir -Seconds 30
if (($setup -join "`n") -notmatch 'status=SUCCEEDED exit_code=0') { throw 'Board directory setup did not finish' }
$sshOptions = @('-o','BatchMode=yes','-o','ConnectTimeout=15')
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Video).Hash.ToLowerInvariant()
$videoName = 'video_' + $hash + [IO.Path]::GetExtension($Video)
& scp @sshOptions (Resolve-Path -LiteralPath $Video).Path "${alias}:$remoteRoot/$remote/inputs/$videoName"
if ($LASTEXITCODE -ne 0) { throw 'Video upload failed' }
$cameraArgument = '--approximate-camera'
if ($Camera) {
    $suffix = [IO.Path]::GetExtension($Camera).ToLowerInvariant()
    if ($suffix -notin @('.yaml','.yml','.json')) { throw 'Camera must be YAML or JSON' }
    $cameraHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $Camera).Hash.ToLowerInvariant()
    $cameraName="camera_$cameraHash$suffix"
    & scp @sshOptions (Resolve-Path -LiteralPath $Camera).Path "${alias}:$remoteRoot/$remote/inputs/$cameraName"
    if ($LASTEXITCODE -ne 0) { throw 'Camera upload failed' }
    $cameraArgument = "--camera $remote/inputs/$cameraName"
}
$modules = @('__init__.py','geometry.py','ply.py','video.py','reconstruct.py','replay.py') | ForEach-Object { Join-Path $PSScriptRoot "../$_" }
& scp @sshOptions @modules "${alias}:$remoteRoot/runtime/dense/app/dense/"
if ($LASTEXITCODE -ne 0) { throw 'Geometry source upload failed' }
& scp @sshOptions (Join-Path $ProjectRoot 'orb60/scripts/run_slam_network.py') "${alias}:$remoteRoot/runtime/dense/app/dense/scripts/"
if ($LASTEXITCODE -ne 0) { throw 'Tracking entry upload failed' }
$command = 'set -e' + "`n" + 'export PYTHONPATH="$PWD/runtime/dense/app"' + "`n" + 'export RKNN_LOG_LEVEL=1' + "`n" +
    "python3 -m dense.reconstruct --video $remote/inputs/$videoName $cameraArgument --output $remote/result --slam-root vendor/ORB_SLAM3 --fpga-host '$FpgaHost' --network-runner runtime/dense/app/dense/scripts/run_slam_network.py --worker runtime/dense/midas-small-fp16/build/dense_npu_worker --model runtime/dense/midas-small-fp16/depth.rknn --npu-acceptance runtime/dense/midas-small-fp16/acceptance.json"
$response = & powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec $command -Name dense-modeling -Seconds $Seconds
$response | Write-Output
if (($response -join "`n") -match 'job_id=([a-zA-Z0-9_-]+)') {
    @{ job_id=$Matches[1]; output="$remoteRoot/$remote/result"; video_sha256=$hash } |
        ConvertTo-Json | Set-Content -Encoding UTF8 $record
} else { throw 'No durable modeling job ID returned' }
if ($LASTEXITCODE -ne 0) { throw 'Modeling failed; inspect the retained job log' }
