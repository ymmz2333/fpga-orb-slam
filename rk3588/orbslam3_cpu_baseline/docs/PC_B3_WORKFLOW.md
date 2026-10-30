# B3 改在电脑执行

本轮实现均为 PC/PS 软件：版本复现、特征比对、监督和评估；不实现 PL 或修改
SLAM 跟踪、建图、优化算法。源代码以 D:\pld 为准，WSL 的
`/home/slam/orbslam3_cpu_baseline` 是生成的编译/运行副本，不在副本内开发。

## 当前权限与门禁

RK3588 P1 已 FAILED。恢复稳定前不得在板上编译、运行 SLAM、实验或压力测试。
只读取已有 Git 对象和归档；原始相机数据使用电脑原件。

PC0 → PC1 → P2/P3 → B3。任何数据损坏嫌疑或预检不通过都停止正式批次。
2026-10-05 用户取消电脑压力测试：以 `pc0_worker.py --skip-memory` 记录
SKIPPED_BY_USER，继续编译及算法预检，不能把跳过标为硬件测试通过。
此前 PC0 压力测试的 FAILED 保留；板上 P1 的 FAILED 和禁运行约束不变。
PC0 的后台 worker **不会自动启动 B3**，不能把依赖或编译成功当成所有预检通过。

## PC0 复现

Windows 已通过项目环境检查；安装 Ubuntu-20.04 / WSL2，并记录 Windows 主机
CPU、核数、内存、磁盘、电源方案。WSL 原 NAT 配置出现 DNS 超时且无法访问
Windows 的 localhost 代理；本机 `.wslconfig` 使用 mirrored、dnsTunneling、
autoProxy，备份/修改记录保存在 `runtime/pc/`，不把本机配置写进源码。

依赖安装：`bash scripts/pc0_dependencies.sh`（WSL root）。要求 GCC 9.4、
Eigen 3.3.7、Boost 1.71；OpenCV 4.5.5 和 Pangolin v0.8 由源码编译。
保留 apt 原始失败和重试日志，不把网络下载失败归为缺少包或编译错误。

ORB 源码读取自板上原有 Git 对象并保存为电脑上的 `runtime/pc/orb_b2.bundle`：
实际 B2 提交 `d3e50c03fc194272c70cb482fd807a025cf7a5cf`，其 C1 父提交
`de62fc00196dc286b5a61b8a1cee57a8cdb6b7c4`，含 0001～0011。
电脑此前本地提交与这两提交的代码差异仅为行尾（忽略行尾后 diff 为空），
但本轮仍使用实际 B2 Git 对象。

`prepare_pc_inputs.py` 复制三段数据到 WSL：两段 Tello 的全部 3957 张 PNG
同时与 C1 清单、P1 已归档板上 SHA256 对比；MH01 的 3682 张 cam0 PNG 与
电脑 ZIP 原条目 SHA256 对比，时间戳与 A2 板上清单对比。当前电脑归档缺少
MH01 板上逐图 SHA256，报告明确记为待补核对，不宣称已通过该项。
不解码或二次编码；不修改电脑原件。

后台准备 worker 串行执行：30 分钟 stressapptest（启动时 MemAvailable 的70%）→
源码编译（Release/O3、j2）→环境、ldd、二进制 SHA256 记录。
内存记录需真实 exit=0、Status PASS、0 hardware incidents、持续至少1800秒；
不满足则不进入编译。结束或失败恢复原 Windows 电源方案。
Windows 协调器运行期间使用临时 SetThreadExecutionState 请求保持系统和显示器
活跃，结束释放；高性能电源方案本身不能防止自动待机。仍须接电并保持笔记本
开盖，不手动睡眠。内存样本同时记录 UTC 和 monotonic，以区分待机与真实活跃测试。
2026-10-05 首次完整尝试被 Modern Standby 中断：工具0错误/PASS，实际活跃
333.845秒，故原 FAILED 保留，补做完整1800秒，不能直接改判通过。

查询（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File D:\pld\rk3588\orbslam3_cpu_baseline\scripts\pc.ps1 status
powershell -ExecutionPolicy Bypass -File D:\pld\rk3588\orbslam3_cpu_baseline\scripts\pc.ps1 log
```

## PC1 与 P2

独立生成器有两个独立编译目录：`b2_candidates_legacy` 的 lapping 上界为0，
仅用于与旧 B2 文件比较；`b2_candidates_corrected` 上界1000，与单目 Frame 一致。
两者不改变选点、描述子或设计候选；原 B2 归档不覆盖。
旧数组顺序差异与跨平台浮点差异分别记录。B3 仅使用 corrected 特征库。

三段前600帧、九种文件候选、normal/initialization 两套全部核对；不把仅有 SHA
对比称为已执行逐字节 memcmp。需要分析的差异从已有归档取字节内容，按头字段、
关键点字段、描述子差异和位翻转分类；疑似板上损坏时停止。

P2 的 dump 是原版提取路径的诊断导出，导出实际选用提取器和另一个提取器；
不作为 native 正式基准。逐帧核对前150帧全部字段/描述子以及 FeatureTimeStats
记录的实际 role。源码选择条件除状态外还有 `(lastID-initID)<mMaxFrames`；
注入按整数纳秒文件名取数据，头部再次校验时间戳。native/V0 三次600帧对照
使用关闭 viewer、原版实时等待，不替换失败。

## P3

0012 仅在示例程序测量区间之后 flush 每帧 feature/map/tracking CSV（以及头部），
不改算法和实时节奏；需编译和 native/MH01 前600帧复核后才能验收。

`run_pc_slam.py` 限制四个 WSL lscpu 报告的不同 CORE（当前代表CPU为0,2,4,6），
并保存实际亲和性。连续120秒没有新完成帧触发看门狗；总上限为120秒启动余量
加序列时长的6倍。先保存各线程 wchan/status，再 gdb 全线程栈，最后 SIGINT，
15秒仍未退出才 SIGKILL。GDB 捕获失败不能通过 P3。

MIN/20:06 前600帧三次不改参数或种子。PC不复现板上卡死时只记未复现，
不据此宣布板上问题已修复。旧错误文本保留，更正说明另列。

## 正式批次范围（尚未启动）

第一轮 native/V0/P1/P2/F/G/A8/A32/B/MIN × 三段 × 五次 =150次，按序号轮转。
之后 MH01 [90,92) 秒缺帧测试另50次；无跳帧对照配对使用第一轮同候选同序号
的50次 MH01 原序列，不复用板上旧结果。记录实际是否触发丢失，不能把未丢失
计为重定位成功。推荐组合第二轮由用户选择。

所有输出注明 **x86 PC / WSL2**；Tello 注明 **借用内参，未本机标定**，轨迹形状
正式标定后需重算。PC耗时仅存为看门狗/健康信息，不输出性能或FPGA加速结论。
正式批次后台启动，确认首次运行正常后结束对话，不在运行期间轮询。
