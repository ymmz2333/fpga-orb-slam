# A3 后台参数矩阵

实现选择：全部为电脑 / RK3588 软件调度与统计，复用已验证的 ORB-SLAM3 CPU 二进制，不修改 PL 或算法实现。
ORB 提交 cf36b06，基准 752×480、1000 特征、8 层；其余五组只改变一个维度。
376×240 用 Settings 的 newWidth/newHeight，原始内参保持不变；生效内参应为
fx=229.327、fy=228.648、cx=183.6075、cy=124.1875，完成后自动核对实际打印值。
初始化提取器为 5*nFeatures：500/1000/1500 对应 2500/5000/7500。

## 配置与启动

电脑端加载 D:\pld 的 scripts/project_env.ps1，并在本项目目录执行：

```powershell
& $ProjectPython scripts/prepare_a3.py
scp -r configs/a3 rk3588:orbslam3_cpu_baseline/configs/
rk start 'python3 scripts/batch_a3.py --batch MH01_matrix_passive_01 --cooling-note "heatsink installed; no fan or fan not rotating"' -Name a3-matrix
rk exec 'python3 scripts/check_a3_started.py --batch MH01_matrix_passive_01' -Name a3-start-check -Seconds 5
```

初次确认正常跟踪后不再轮询日志。整个板上批次由已有持久 SSH worker 调度，SSH 断开、电脑休眠不影响板上批次。
输出只写 runtime/a3/<batch>/；不要重复启动相同 batch，目录存在即拒绝。
轮转顺序：baseline_752x480、half_376x240、features_500、features_1500、levels_4、levels_1；每个运行序号轮转六组，共五轮。
每次跑完整个 MH01，关闭 viewer，保留官方按时间戳等待；绑定确认的 A76 CPU4～7，三组 policy 临时设 performance。
沿用 A2 的开始前冷却到所有温区不超过 45°C，等待最多十分钟；半秒记录温度、实际频率、频率上限、CPU cooling state。
run_a2.py 新增可选 settings 和 stop-on-frequency-drop，原 A2 默认行为不变。
检测 A76 降频或 CPU 热限制时终止本次进程、恢复 governor、标为 THERMAL_PAUSE，停止批次；不补跑。
算法崩溃、初始化失败或跟踪丢失保留原序号，继续其他配置；准备失败、无法冷却或 governor 恢复失败则暂停等待诊断。
没有改变随机种子，没有挑选结果。批次退出不等于全部跟踪成功。

## 用户回来后计算 ATE 和摘要

```powershell
& $ProjectPython scripts/finish_a3.py --batch MH01_matrix_passive_01 --dataset (Join-Path $ProjectRoot 'data/euroc/MH_01_easy')
& $ProjectPython scripts/summarize_a3.py reports/a3/MH01_matrix_passive_01
& $ProjectPython scripts/summarize_a3.py reports/a3/MH01_matrix_passive_01 --csv-only
& $ProjectPython scripts/report_a3.py --batch MH01_matrix_passive_01
```

前者传回原始输出，复用 A2 分状态统计与电脑 evo Sim3 / NumPy 交叉验证；初始化 / 丢失单独统计，模块排除对齐零。
写入 results_exp1.csv、summary.csv，保留 raw/ 下每次日志、时间统计、状态、温度频率、YAML、ATE 及校验信息。
--csv-only 只读取 results_exp1.csv 重建 summary.csv，不依赖原始数据目录或板子。
汇总包含 A2 已验收的五次 600×350 官方非等比缩放参考行，不重跑 A2。
正常帧计算 ORB 逐帧比值中位数及 sum(ORB)/sum(Total)，报告 Total >33/>50 ms 比例。
Total 在缩放配置中包含内部 resize，但当前 Image Resize 列不能单独反映 Settings 内部缩放耗时。
未初始化、无轨迹、运行中断、分析出错的指标留空并记录原因，不能当作零。
每次仅回传一行：配置、序号、输入是否跑完、ATE、是否降频；有异常再查看详细日志。
完成全部分析后生成中文报告与每配置五次中位数 / 最小 / 最大值，回答特征数、分辨率、层数影响及 752×480 相对 A2 的 ORB 占比变化。
