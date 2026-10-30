$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\scripts\project_env.ps1')
$experimentRoot = Split-Path $PSScriptRoot -Parent

try {
    $receipt = Get-Content -LiteralPath (Join-Path $experimentRoot 'runtime\pc\golden_layer_latest_launch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $decisionRoot = Join-Path $ProjectRoot 'orb_frontend_golden\decision'
    $state = Get-Content -LiteralPath (Join-Path $decisionRoot ($receipt.batch + '_coordinator\state.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
    $phase = @{preparing='准备'; power='设置电源'; build_native='构建'; verify_linkage='动态链接检查'; runtime_preflight='运行预检'; launch_decision='启动正式流程'; decision_pipeline='正式流程'; await_user_layer_choice='完成，等待选择层数'}[$state.phase]
    if (-not $phase) { $phase = $state.phase }
    $completed = 0
    $failedSlots = 0
    $detail = ''
    $batchStatePath = Join-Path $decisionRoot ($receipt.batch + '\batch_state.json')
    if (Test-Path -LiteralPath $batchStatePath) {
        $batchState = Get-Content -LiteralPath $batchStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $completed = $batchState.completed
        if ($null -ne $batchState.failed_slots) { $failedSlots = $batchState.failed_slots }
        switch ($batchState.phase) {
            'resume_preparation' { $phase = '恢复已保存进度' }
            'resume_prepared' { $phase = '续跑准备完成' }
            'verify_reused_inputs' {
                $phase = '校验复用输入'; $detail = $batchState.current
                if ($null -ne $batchState.packets_to_verify) { $detail += "，特征校验 $($batchState.verified_packets)/$($batchState.packets_to_verify)" }
            }
            'build_native' { $phase = '构建（正式流程）' }
            'generate_g1_corpus' { $phase = '生成全序列特征'; $detail = $batchState.current; if ($batchState.generated_frames) { $detail += "，已生成 $($batchState.generated_frames) 帧" } }
            'historical_selected' { $phase = '统计G1已有点数与空格；重建缺失的native逐层数' }
            'generate_t2_corpus' { $phase = '生成并核对T2全序列特征'; $detail = $batchState.current }
            'decision_runs' {
                $phase = 'SLAM正式运行'; $detail = $batchState.current
                $runMetaPath = Join-Path $decisionRoot ($receipt.batch + '\runs\' + $batchState.current + '\run_metadata.json')
                if (Test-Path -LiteralPath $runMetaPath) {
                    $runMeta = Get-Content -LiteralPath $runMetaPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($null -ne $runMeta.completed_frames) { $detail += "，当前帧 $($runMeta.completed_frames)/$($runMeta.expected_frames)" }
                }
            }
            'waiting_exclusive_slam' { $phase = '等待其他SLAM任务释放资源' }
            'report' { $phase = '生成报告' }
        }
        if ($batchState.status -eq 'FAILED') { $state.status = 'FAILED'; $state.error = $batchState.error }
        if ($batchState.status -eq 'FINISHED_AWAIT_LAYER_DECISION') { $state.status = $batchState.status; $phase = '报告完成，等待选择层数' }
    } elseif ($state.phase -eq 'runtime_preflight') {
        $preflightPath = Join-Path $decisionRoot ($receipt.batch + '_preflight\state.json')
        if (Test-Path -LiteralPath $preflightPath) {
            $preflight = Get-Content -LiteralPath $preflightPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $detail = $preflight.phase
            if ($preflight.status -eq 'FAILED') { $state.status = 'FAILED'; $state.error = $preflight.error }
        }
    }
    $termination = '运行中，未终止'
    if ($state.status -eq 'FAILED') { $termination = '已失败并终止'; $detail = $state.error }
    elseif ($state.status -eq 'FINISHED_AWAIT_LAYER_DECISION') { $termination = '已完成并停止' }
    elseif (-not (Get-Process -Id $receipt.windows_pid -ErrorAction SilentlyContinue)) { $termination = '协调器已退出，未记录可靠完成状态'; $state.status = 'LOST' }
    $detail = ($detail -replace 'flight_20261004T184929_998838_6bb93c56','Tello18:49' -replace 'flight_20261004T200648_509768_918b85a4','Tello20:06' -replace '[\r\n]+',' ')
    $suffix = if ($detail) { "；$detail" } else { '' }
    Write-Output "$termination；阶段：$phase；正式槽位：$completed/90；失败槽位：$failedSlots$suffix"
} catch {
    Write-Output ('状态查询失败：' + ($_.Exception.Message -replace '[\r\n]+',' '))
    exit 1
}
