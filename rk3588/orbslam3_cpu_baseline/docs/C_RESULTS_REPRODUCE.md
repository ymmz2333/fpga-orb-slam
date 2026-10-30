# C2 收集、统计和内参视觉检查

所有结果为“临时内参，待标定后重跑”；没有真值，不计算 ATE。当前批次已结束，以下命令不启动新的 SLAM 实验。

从 `D:\pld` 执行，Python 由项目环境派生：

```powershell
. scripts/project_env.ps1
Set-Location rk3588/orbslam3_cpu_baseline
# 首次收集才加 --download；raw_manifest.csv 校验后保留原字节。
& $ProjectPython scripts/finish_c.py --batch C2_provisional_20261005_0152
& $ProjectPython scripts/export_c_loss_images.py --report reports/c2/C2_provisional_20261005_0152 --datasets runtime/c/datasets/TT_C1_01
& $ProjectPython scripts/review_c_losses.py --report reports/c2/C2_provisional_20261005_0152
& $ProjectPython scripts/report_c_results.py --report reports/c2/C2_provisional_20261005_0152
```

`raw/` 不写入派生统计，`analysis/` 是可再生副本。`results_c2.csv` 为逐次结果，`summary.csv` 为三次中位数/最小/最大；`timing_by_state.csv` 分正常/初始化/丢失，`module_statistics.csv` 保留模块补0排除数；`trajectory_consistency.csv` 保留无法配对的失败原因。`loss_review/observations.csv` 为人工视觉观察输入，联系图和上下文可重新生成；不把观察标签当作确定因果。

报告额外读取已保存的 `original_integrity.json`（本轮63个原文件SHA256/只读核对）、`intrinsics_preview.json`（映射计算、27帧输入校验）与 `launch.json`。这些是验收证据，重新生成派生图表不改写它们；图像观察程序属于电脑/PS软件，不改变PL逻辑。

内参检查：

```powershell
# 从项目根 D:\pld 执行；生成后用默认浏览器打开，不需要网络。
powershell -ExecutionPolicy Bypass -File rk3588/orbslam3_cpu_baseline/scripts/open_intrinsics_preview.ps1
```

可使用 `-BuildOnly` 仅生成。生成页面位于实验仓库 `runtime/c/visual_checks/provisional_intrinsics/index.html`，其 `assets/` 必须与 HTML 一起保留。选择9段视频的27个样本，拖动分界线、整帧切换，或打开参考网格观察书架等直线。

保持原尺寸与同一 K，不使用最优新 K，不裁剪或编码视频。Brown–Conrady 映射用独立公式核对，零畸变恒等和输入 SHA256 在生成时检查。像素位移是临时畸变模型造成的几何变化，不能用于证明借用内参准确。单目 SLAM 实际在原图提取 ORB，再校正关键点坐标；整幅图校正只是视觉检查。

本轮停止在 C。棋盘格标定脚本 `scripts/calibrate_camera.py` 已就绪；实际内角点数、方格边长和视频到位后运行，随后重新生成正式内参并按每段5次重跑。B2 还需要用户决定数据集。
