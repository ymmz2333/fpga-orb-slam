$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\scripts\project_env.ps1')
$experimentRoot = Split-Path $PSScriptRoot -Parent
$batchId = 'H1_H2_v095_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
$py = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$pyw = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$linuxRoot = (& wsl -d Ubuntu-20.04 -u root -- wslpath -u ($ProjectRoot -replace '\\','/')).Trim()
& wsl -d Ubuntu-20.04 -u root -- "$linuxRoot/orb_frontend_golden/.venv-wsl/bin/python" "$linuxRoot/rk3588/orbslam3_cpu_baseline/scripts/h_round.py" --batch $batchId --prepare-only
if ($LASTEXITCODE -ne 0) { throw 'H1/H2准备未通过，未启动后台运行' }
$worker = Join-Path $PSScriptRoot 'h_round_worker.py'
$process = Start-Process -FilePath $pyw -ArgumentList @(('"' + $worker + '"'), '--batch', $batchId) -WindowStyle Hidden -PassThru
$receipt = @{batch=$batchId; windows_pid=$process.Id; scope='H1/H2 90 slots; x86 PC / WSL2'; started=(Get-Date).ToString('o')}
$latest = Join-Path $experimentRoot 'runtime\pc\golden_layer_latest_launch.json'
$receipt | ConvertTo-Json | Set-Content -LiteralPath ($latest + '.tmp') -Encoding UTF8
Move-Item -LiteralPath ($latest + '.tmp') -Destination $latest -Force
$coordinator = Join-Path $ProjectRoot ('orb_frontend_golden\decision\' + $batchId + '_coordinator')
for ($attempt=0; $attempt -lt 15; $attempt++) {
    if (Test-Path -LiteralPath (Join-Path $coordinator 'state.json')) { break }
    if ($process.HasExited) { throw '协调器启动即退出，正式状态待诊断；没有重启' }
    Start-Sleep -Seconds 1
}
if (-not (Test-Path -LiteralPath (Join-Path $coordinator 'state.json'))) { throw '协调器未记录启动状态，不自动重启' }
$notifier = Join-Path $PSScriptRoot 'golden_layer_notify.py'
$notify = Start-Process -FilePath $pyw -ArgumentList @(('"' + $notifier + '"'),'--batch',$batchId,'--pid',$process.Id,'--label','"H1/H2 层数与双阈值决策轮"') -WindowStyle Hidden -PassThru
$receipt.notifier_pid=$notify.Id
$receipt | ConvertTo-Json | Set-Content -LiteralPath $latest -Encoding UTF8
$receipt | ConvertTo-Json -Compress
