# A2：电脑准备与评估，RK3588 实测

用户已验收 A1、授权 A2，A2 完成后停下，A3 需再次确认。
架构选择：网络、数据处理、轨迹评价和统计采用电脑/PS 软件，不修改 FPGA。

## 连接与输入

`rk check` 检查免密 SSH。长任务输出留在板上，使用 `rk status/wait/log` 获取摘要。
主机配置在忽略的 local_board.json/native SSH config，不写凭据到源码。

浏览器下载的 ZIP 放在项目根目录。只选择 MH_01_easy；当前收到的独立 ZIP 根目录为 mav0。
不解压其他序列。安全检查路径、重复成员、符号链接；流式解压会核验 ZIP CRC。
生成 transfer_manifest.json（压缩包 SHA-256、每文件 SHA-256），传输后逐文件复核。

```powershell
.\scripts\a2_pc.ps1 -Action extract
scp -q rk3588:orbslam3_cpu_baseline/vendor/ORB_SLAM3/Examples/Monocular/EuRoC_TimeStamps/MH01.txt reports/a2/MH01.txt
.\scripts\a2_pc.ps1 -Action validate
.\scripts\a2_pc.ps1 -Action transfer
```

板上数据为 ~/data/euroc/MH_01_easy。图像文件集必须等于 cam0/data.csv 的唯一文件名集合，
真值和相机标定必须存在，每个官方 MH01 时间戳必须有 752×480 PNG。
官方时间间隔为名义 20 Hz，实测相邻值 49,999,872～50,000,128 ns，保留原始值。

## 编译与依赖

```powershell
rk exec 'bash scripts/build_a2.sh' -Name a2-build
.\scripts\a2_pc.ps1 -Action install-evo
```

build_a2.sh 应用 1～8 号补丁、j2 构建并清理临时 swap；四个 ldd 检查仅解析到 OpenCV 4.5.5。
系统存在 4.2 运行库与 python3-opencv，未发现 4.2 开发包，当前产物没有混链。
再次配置时必须指定 install 前缀。不要自行卸载系统包。

evo 仅安装在电脑的项目 .venv（CPython 3.12.12），清华镜像实际安装 v1.37.1。
冻结环境见 reports/a2/evo-pc-requirements.txt。RK3588 不安装 evo，不需要公网下载。
若安装失败可显式调用 evaluate_a2.py --numpy-only，报告会标记为临时 Umeyama Sim3 评价，
后续必须用 evo 交叉验证。当前每次正式 evo 结果均同步与独立 NumPy 误差逐项比较。

## 真实运行

A2 官方 EuRoC.yaml 保持原样：输入 752×480，实际跟踪 600×350 非等比缩放。
Settings 自动调整内参；Total 包含 Image Resize 和 TrackMonocular，不包括 imread/帧间等待。
原例程按官方时间戳 usleep 的实时节奏保持不变。A3 不在本阶段运行。

```powershell
.\scripts\a2_pc.ps1 -Action run -Batch MH01_600x350_passive_01 -CoolingNote '已装散热器，风扇未转/无风扇，用户确认'
```

替换 CoolingNote 为用户实际确认状态。此次用户确认已装散热器、无风扇或风扇未转。
程序确认 MIDR 后绑定 A76 CPU4～7，采样监督进程绑定 A55。
将 policy0/4/6 设为 performance，退出恢复原 governor。采样间隔 0.5 s。
记录温度、当前/上限频率、CPU cooling 状态、运行前后传感器、实际 affinity、源码提交及二进制 hash。
开始前等待温度低于 45°C，最多 10 分钟；单次最多 30 分钟。
这些是控制门槛，不是实验结果。频率下降、限频或 cooling 状态启用的尝试不计入五次有效运行，
保留并补跑，最多十次。TrackingStates.csv 创建到退出的检测窗口包含 shutdown，采用保守排除。
离散采样不能证明样本间绝无瞬时降频。

电脑批量脚本使用已有 durable SSH controller，30 秒轮询，不重复启动仍在运行的作业。
每次完成后 scp 回传原始结果，在电脑统计和 evo 评价，再决定是否继续。
输入/运行/统计/评价失败时停止诊断；ATE >0.10 m 时也停止，这是诊断门槛而非验收值。

## 分帧统计

TrackingStates.csv 与 TrackingTimeStats.txt 逐行对齐，记录 frame_index、序列帧索引、
timestamp_s、state_before/state_after。后者为 System 获取的 Tracking::mState。
状态 -1 未准备、0 无图像、1 未初始化、2 OK、3 RECENTLY_LOST、4 LOST。
初始化成功帧（before=-1/0/1，after=2）仍归初始化；after=3/4 归丢失。
before=2/3/4 且 after=2 归正常，成功恢复帧另外计数。

ORB ext[ms] 是第 3 列，Total[ms] 是第 9 列。仅正常帧计算：

- median(逐帧 ORB/Total)。
- sum(ORB)/sum(Total)。

分母均包含非等比图像缩放。初始化/丢失耗时单列、不报 ORB 占比。
正常帧报告 Total 均值/中位数/P95、ORB 中位数/P95、Total >50 ms 与 >33 ms 比例。
其他模块排除补齐的 0，记录 valid count / excluded_zero。P95 使用 linear 插值。
v1.0 Settings 的内部 resize 未填充 Image Resize 专用向量；该列 0 表示未单独计时，
不能解释为未缩放或耗时为零。实际 resize 位于 TrackMonocular 中，所以计入 Total。
SessionInfo.txt 记录最终 Atlas 地图数；重置次数匹配实际 Tracking 日志，避免重复统计子线程。

## ATE 与复现汇总

f_MH01.txt 的 ns 时间戳用 Decimal 转成 TUM 秒。GT qw/qx/qy/qz 重排为 qx/qy/qz/qw。
机体真值用 cam0/sensor.yaml 的 T_BS 转相机位姿：T_world_cam0=T_world_body*T_body_cam0。
同时保留 body/cam0 两种 TUM 真值。评价命令为：

```text
evo_ape tum groundtruth_cam0.tum camera.tum -as --t_max_diff 0.01 --save_results ape.zip
```

保存命令、输入 hash、日志、误差数组、Sim3 参数及 CSV。NumPy 使用与已安装 evo 相同的
短序列到长序列最近时间匹配（10 ms 容差），不做插值，不删除 evo 接受的重复匹配。
上游 Tracking 在空 pose 的丢失帧会复制前一 pose/时间；相同时间的完全相同导出行保留，
与 evo 官方原始轨迹评价一致，并报告 duplicate_export_rows。不改写时间、不推测位姿；
倒序时间或同一时间对应不同位姿仍报错。
check_gt_reference_a2.py 可将转换后的 cam0 位置逐项与官方仓库 MH01_GT.txt 比较，
结果保存为 CSV/JSON。检查仅针对 APE 使用的位置分量，不声称验证官方参考的全部姿态。

电脑与板上原始结果均在 runtime/a2/<batch>/attempt_XX，电脑 reports/a2/<batch>/runs.csv
保留全部尝试及失败/降频原因，summary.csv 为有效五次结果的中位数/最小/最大。

```powershell
.\scripts\a2_pc.ps1 -Action summary -Batch MH01_600x350_passive_01
.\scripts\a2_pc.ps1 -Action report -Batch MH01_600x350_passive_01
```

summarize_a2.py 仅从 runs.csv 重建汇总，report_a2.py 可从保留的 raw/ 证据重建报告。
合成验证仅证明程序、分组统计与评价数学正确，不能代替真实 MH01 精度或耗时。
五次实际验收通过才可宣布 A2 完成。
