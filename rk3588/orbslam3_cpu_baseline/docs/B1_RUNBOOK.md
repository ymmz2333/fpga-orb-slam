# B1：特征导出与注入（独立于 B2）

源码基线 cf36b06（官方 v1.0-release + 0001～0008）；0009 增加单目接口、独立内存快照、逐帧 I/O 和内点数。
源码和实验仓库均使用 b1/external-features 分支。A3 已验收的库和程序备份到 runtime/b1/accepted-a3。
保留 OpenCV 4.5.5、Pangolin 0.8 及 A3 的 Release 编译设置，不引入新依赖。

## 板上复现

已完成 A1 的源码/依赖环境中：

```bash
bash scripts/build_b1.sh
export LD_LIBRARY_PATH="$PWD/install/lib"
mkdir -p runtime/b1/check
vendor/ORB_SLAM3/Examples/Monocular/feature_io_check runtime/b1/check/codec
python3 scripts/verify_feature_files.py --fixture --corpus runtime/b1/check/codec --output runtime/b1/check/verification
python3 scripts/batch_b1.py --batch MH01_fixed_dmc_01 --cooling-note '已装散热器，没有风扇或风扇未转'
```

最后一项通过已有 rk start 后台工作器启动。不要复用批次 ID/输出目录，不覆盖或替换失败运行。
执行顺序：完整 MH01 dump（每帧正常/初始化两套）→7364 文件独立解析与内存字节比对→五轮 native/inject，各5次。
每轮交错，偶数轮调换先后顺序；dump 耗时不进入正式对比。
双提取器及独立快照需要约 GB 级空间，运行前检查空闲空间。正常提取器1000，初始化提取器5000；其选择完全沿用 Tracking 的逻辑。

752×480 原图、1000特征、8层使用 configs/a3/baseline_752x480.yaml，内参不缩放。
保持实时时间戳等待、关闭 Viewer、A76 CPU4–7（MIDR确认）、CPU performance、DMC performance最高1560MHz。
每次运行前等待所有温区≤45℃，每0.5秒记录温度、CPU当前/上限频率、DMC当前/上限频率。
只改变 governor，不修改 DMC min/max；正常退出或异常后恢复并验证原 governor 和频率上限。
CPU/DMC降频、编译/数据/文件不匹配、恢复失败均暂停批次，保留受影响记录，等待用户决策。
原 A3 使用动态 DDR且没有逐次记录DDR，不重跑；只能作为单列参考，不能把全部差异归因于注入。

## 完成后电脑端

```powershell
. (Join-Path (Resolve-Path '../..') 'scripts/project_env.ps1')
# 使用项目 .venv Python运行下列脚本，路径从项目环境派生。
& $ProjectPython scripts/finish_b1.py --batch MH01_fixed_dmc_01 --dataset ../../data/euroc/MH_01_easy
& $ProjectPython scripts/finish_b1.py --batch MH01_fixed_dmc_01 --dataset ../../data/euroc/MH_01_easy --csv-only
& $ProjectPython scripts/verify_b1_results.py reports/b1/MH01_fixed_dmc_01
& $ProjectPython scripts/report_b1.py reports/b1/MH01_fixed_dmc_01
```

从板上只拉每次输出和校验清单，不传整个特征库/内存快照。ATE在电脑用既有evo做Sim3并用NumPy交叉核验，真值通过cam0外参转换。
输出 reports/b1/<batch>/raw、results_exp3_b1.csv、summary.csv 和 baseline_comparison.csv；所有汇总由 raw 重建。
板端原始文件的SHA256清单raw_manifest.csv需要与批次一同保留，verify_b1_results.py核对256个原始文件及计时/频率/覆盖。
已完成MH01_fixed_dmc_01；结果见reports/b1/MH01_fixed_dmc_01/B1_REPORT.md。B2仍等待用户确认。
跟踪分辨率全部明确标注；原A2 600×350非等比缩放不混入B1基准。

## 计时及状态口径

TrackingStates.csv 与 TrackingTimeStats.txt 和 FeatureTimeStats.csv 均按输入帧对齐。
FeatureTimeStats记录整数纳秒、role、点数、实际提取器调用数（native=1/dump=2/inject=0）、读取/解码/原版提取/写盘/额外提取时间，以及内点数。
正常帧=state_before∈{2,3,4}且state_after=2；首次初始化完成帧计入初始化。内点数仅在正常帧有效，其余−1，避免读取旧值。
报告初始化/正常/丢失数量、GT范围内丢失、GT范围外尾段丢失、结束状态、地图数及内点数分布。
初始化前和丢失的计时单列；模块计时剔除对齐用0，仍保留真实I/O为0的native状态。
native ORB占比给逐帧比值中位数和总耗时比；inject特征槽是读取+解码+调用开销，不能当作ORB算法耗时。
逐帧Total−完整特征槽后再求统计量，得到无提取/无传输的理想剩余耗时；实际FPGA还需要传输和同步。
同DDR条件新native和inject总耗时差是本次主要比较；文件读/解码与理想剩余分开报告。每配置5次取中位数、最小/最大，不挑结果。
正式数据未完成之前，不声明等价性通过或给出加速实测数字。B1完成后停下，不进入B2。
