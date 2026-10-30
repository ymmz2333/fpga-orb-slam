param([ValidateSet('Deploy','Run','Collect')][string]$Stage,
      [Parameter(Mandatory=$true)][string]$Attempt,
      [string]$Samples = 'samples', [string]$Config)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
if ($Attempt -notmatch '^[a-zA-Z0-9_-]+$' -or $Samples -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Unsafe artifact name' }
$rk = Join-Path $ProjectRoot 'rk3588/orbslam3_cpu_baseline/scripts/rk.ps1'
if (-not $Config) { $Config = Join-Path $ProjectRoot 'rk3588/orbslam3_cpu_baseline/local_board.json' }
$board = Get-Content -Raw $Config | ConvertFrom-Json
$alias = $board.sshAlias
$root = $board.remoteRoot
if ($alias -notmatch '^[a-zA-Z0-9_.-]+$' -or $root -notmatch '^(~/|/)[a-zA-Z0-9_./-]+$') { throw 'Invalid SSH settings' }
$build = Join-Path $ProjectRoot 'orb60/build/dense'
$local = Join-Path $build $Attempt
$remote = "runtime/dense/$Attempt"
$sshOptions = @('-o','BatchMode=yes','-o','ConnectTimeout=15')
if ($Stage -eq 'Deploy') {
    $init = & powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec "mkdir -p $remote/sdk $remote/src $remote/inputs" -Name dense-init -Seconds 30 -Config $Config
    $init | Write-Output
    if ($LASTEXITCODE -ne 0 -or ($init -join "`n") -notmatch 'status=SUCCEEDED exit_code=0') { throw 'Directory setup did not finish' }
    & scp @sshOptions (Join-Path $build 'assets/librknnrt.so') (Join-Path $build 'assets/rknn_api.h') "${alias}:$root/$remote/sdk/"
    if ($LASTEXITCODE -ne 0) { throw 'SDK upload failed' }
    & scp @sshOptions (Join-Path $PSScriptRoot '../npu/worker.cpp') (Join-Path $PSScriptRoot '../npu/CMakeLists.txt') "${alias}:$root/$remote/src/"
    if ($LASTEXITCODE -ne 0) { throw 'Worker upload failed' }
    & scp @sshOptions (Join-Path $local 'depth.rknn') "${alias}:$root/$remote/"
    if ($LASTEXITCODE -ne 0) { throw 'Model upload failed' }
    $inputRoot = Join-Path $build $Samples
    $names = (Get-Content -Raw (Join-Path $inputRoot 'samples.json') | ConvertFrom-Json).frames.id
    [IO.File]::WriteAllText((Join-Path $inputRoot 'names.txt'), ($names -join "`n")+"`n", [Text.UTF8Encoding]::new($false))
    $files = @((Join-Path $inputRoot 'names.txt')) + @(Get-ChildItem $inputRoot -Filter '*.input.f32' | ForEach-Object FullName)
    & scp @sshOptions @files "${alias}:$root/$remote/inputs/"
    if ($LASTEXITCODE -ne 0) { throw 'Input upload failed' }
    $command = 'set -e' + "`n" + 'cmake -S '+$remote+'/src -B '+$remote+'/build -DRKNN_PRIVATE_ROOT="$PWD/'+$remote+'/sdk" -DCMAKE_BUILD_TYPE=Release' + "`n" + 'cmake --build '+$remote+'/build -j2' + "`n" + 'ldd '+$remote+'/build/dense_npu_worker'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec $command -Name dense-build-worker -Seconds 30 -Config $Config
    if ($LASTEXITCODE -ne 0) { throw 'Worker build failed; inspect retained job' }
} elseif ($Stage -eq 'Run') {
    $command = 'set -e' + "`n" + 'export RKNN_LOG_LEVEL=1' + "`n" + "$remote/build/dense_npu_worker $remote/depth.rknn $remote/inputs $remote/inputs/names.txt $remote/output"
    $result = & powershell -NoProfile -ExecutionPolicy Bypass -File $rk exec $command -Name dense-npu-gate -Seconds 30 -Config $Config
    $result | Write-Output
    $text = $result -join "`n"
    if ($text -match 'job_id=([a-zA-Z0-9_-]+)') {
        @{ job_id=$Matches[1]; remote=$remote; samples=$Samples } | ConvertTo-Json |
            Set-Content -Encoding UTF8 (Join-Path $local 'board-job.local.json')
    } else { throw 'Missing durable job identifier' }
    if ($LASTEXITCODE -ne 0) { throw 'NPU worker failed; retain the durable job and logs' }
} else {
    $job = Get-Content -Raw (Join-Path $local 'board-job.local.json') | ConvertFrom-Json
    $result = & powershell -NoProfile -ExecutionPolicy Bypass -File $rk status $job.job_id -Config $Config
    $result | Write-Output
    if ($LASTEXITCODE -ne 0 -or ($result -join "`n") -notmatch 'status=SUCCEEDED exit_code=0') { throw 'No trustworthy completed NPU run; do not collect as passing' }
    $out = Join-Path $local 'board'
    New-Item -ItemType Directory -Force $out | Out-Null
    & scp @sshOptions -r "${alias}:$root/$remote/output/." $out
    if ($LASTEXITCODE -ne 0) { throw 'Result download failed' }
    & scp @sshOptions "${alias}:$root/runtime/ssh_jobs/$($job.job_id)/state.json" (Join-Path $out 'job-state.json')
    if ($LASTEXITCODE -ne 0) { throw 'Job state download failed' }
}
