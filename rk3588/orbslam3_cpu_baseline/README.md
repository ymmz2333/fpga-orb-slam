# RK3588 ORB-SLAM3 CPU 基线

日常连接和长任务操作见 [SSH 简化流程](docs/SSH_WORKFLOW.md)：
`rk exec '命令'`、`rk status <job_id>`、`rk log <job_id>`。

当前 A1/A2/D/A3 已验收，B0 只读分析及 B1 特征导出/注入开发使用 `b1/external-features` 分支。
采用 CPU/软件实现；B1 流程见 [运行说明](docs/B1_RUNBOOK.md)、[特征格式草案](docs/B1_FEATURE_FORMAT.md)。
完整 B1 后台批次与电脑端 ATE 已检查，报告见 [B1 结果](reports/b1/MH01_fixed_dmc_01/B1_REPORT.md)。
特征字节一致性通过；两组精度相近，GT范围外尾段丢失次数差异已单列保留。等待用户验收，不自动进入 B2。
不改变现有 FPGA 全景拼接实现。板上工作目录为 `~/orbslam3_cpu_baseline`。

## 固定版本与分支

|组件|版本|官方 commit|
|---|---|---|
|ORB-SLAM3|v1.0-release|`0df83dde1c85c7ab91a0d47de7a29685d046f637`|
|Pangolin|v0.8|`aff6883c83f3fd7e8268a9715e84266c42e2efe3`|
|OpenCV|4.5.5|`dad26339a975b49cfb6c7dbe4bd5276c9dcb36e2`|

Pangolin v0.8 按用户的版本偏好选择，已通过实际 C++14 编译和无可视化运行检查。
系统 apt 的 OpenCV 4.2 不满足 ≥4.4，故在独立 `install/` 前缀构建 4.5.5。
源码获取脚本使用官方 Git tag 和下载归档，并验证完整 Git tree。
Pangolin 的可选 pybind11/vcpkg 子模块不用于本次关闭 Python/tools 的构建。

本复现仓库分支为 `a1/build-environment`。板上 ORB 修改在
`a1/rk3588-cpu-baseline` 分支，七项修改分别提交，补丁见 `patches/`。

## 从干净目录复现 A1

将本仓库 scripts 和 patches 放到板上相同目录结构，执行：

```bash
cd ~/orbslam3_cpu_baseline
python3 scripts/environment_snapshot.py
bash scripts/install_apt.sh
BUILD_JOBS=2 bash scripts/build_a1.sh
```

需要可用的 `sudo -n` 和 GitHub/Ubuntu 软件源网络。默认两个编译任务。
构建脚本启用 8 GiB 临时 swap，退出时关闭并删除本项目的 swap 文件；不修改 fstab。
`build_a1.sh` 执行源树验证、补丁提交、OpenCV/Pangolin/第三方库/ORB 编译、
OpenCV 实际运行探针、五次启动与计时输出检查、环境快照和证据收集。
运行检查使用唯一 suite ID，旧合成输出不会被复用。
完整下载和干净构建的一键流程尚未从另一台空白板验证；本板各子步骤及最终产物已实际执行。

仅重复 A1 运行验收：

```bash
bash scripts/diagnose_opencv.sh
bash scripts/verify_a1_runtime.sh
python3 scripts/collect_a1_evidence.py
```

Linux 脚本统一加载 `common.sh` 中的安装前缀与 `LD_LIBRARY_PATH`；直接启动二进制也需要
相同运行环境。证据收集加载相同动态库目录，并要求 ldd 无缺失依赖。
构建主程序仅指定 `mono_euroc` target，生成该示例及 `libORB_SLAM3.so`。

## Windows SSH 与结果位置

`scripts/board.ps1` 加载主项目 `scripts/project_env.ps1`。板地址、用户和相对于
主项目根目录的密钥路径写在忽略的 `local_board.json` 中，字段为 `host/user/keyPath`。
配置和凭据不提交。用 `-Command` 执行板上命令；`-Upload/-Download/-RemotePath` 传单个文件。

生成源码、构建、安装、runtime 和 logs 均忽略。紧凑的阶段证据保留在 `reports/a1/`：

- `A1_REPORT.md`：环境、修改、验收、已知问题及下一阶段决策。
- `acceptance.csv`、`a1-runtime-runs.csv`：逐项验收和四项检查 × 五次重复。
- `environment*.csv`、`source_trees.csv`：实际环境、版本和源树验证。
- `smoke_run_*/tracking_times.csv`：合成输入的实测逐帧计时，单位毫秒。
- `orb_source_diff.patch`、`diff_summary.txt`、`orb_commits.csv`：完整差异与提交记录。
- `failures/`、`build_logs/`：初始失败诊断和最终构建日志。

## A1 的范围

合成输入每次 24 帧，只检查加载、ORB 提取、无可视化启动、结束和统计输出。
输入未产生关键帧，不能证明定位、重定位、EuRoC 精度或性能基线。
`TrackingTimeStats.txt` 第三列 `ORB ext[ms]` 是 ORB 提取耗时，
第九列 `Total[ms]` 是逐帧跟踪总耗时；不包含外部 imread 和播放等待。
`ExecMean.txt` 的 `ORB Extraction` 是均值与标准差，不是中位数或 P95。
未执行的模块可能没有样本或输出 NaN，不将其解释为性能结果。

A2/A3 必须每配置至少五次，在阶段之间等待用户确认。
v1.0 官方 `EuRoC.yaml` 原生支持缩放，并默认设为 600×350；
进入 A2 前确认保留官方默认还是改为用户指定的 752×480 基准。
以上是 A1 的验收范围；A1 合成运行不能替代后续数据集实验。

## 当前阶段：实拍数据 C0（2026-10-04）

A2、A3、D 已获用户验收；B1 已完成并保留在 `reports/b1/MH01_fixed_dmc_01/`。
新增实拍数据 C 阶段先于 B2，取消 H.264 退化版 MH01 方案。
C0 的数据保护、码流与时间戳盘点见 `reports/c0/C0_REPORT.md`，
OAFD 借用参数候选见 `configs/c/tello_oafd_960x720_provisional.yaml`。
这份 YAML 是临时内参，尚未标定本机，不能声明本机重投影误差或标定通过。
本阶段尚未运行 C2；C0 后等待用户确认分辨率与时间戳方案。
详见 `docs/C_STAGE_PLAN.md`；正式标定后才开始 B2。
