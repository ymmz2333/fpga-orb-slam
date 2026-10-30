# ORB Studio 原生上位机

两阶段摄像头演示新增可选 `--demo-controller http://<RK地址>:5610`。
入口为 `orb60/demo_bridge/run_viewer.ps1`，支持异构建图、地图交接、本地重定位和停止。
该模式不会自动打开历史录像；切到 Zynq 本地定位后提示观看 HDMI。
实现及当前未完成的板级门禁见 `../demo_bridge/README_ZH.md`。

Windows 桌面界面使用 PySide6、pyqtgraph 和 OpenGL。FPGA 负责 ORB 特征，ORB-SLAM3 可运行在鲁班猫或电脑 WSL；Windows 绘制界面。保持现有 4PPC / 150 MHz bitstream 和 PS 服务。

## 电脑网线直连 FPGA：WSL 实时模式

双击根目录 `Launch-ORB-WSL-Live.cmd`。WSL 运行 SLAM，Windows 原生窗口绘图，不依赖鲁班猫。入口自动探测能访问 FPGA 的 WSL 有线接口，通过端口 5600 流水发送图像并接收实体 FPGA 特征，随后将位姿和地图从 WSL 本机端口 18767 送到窗口。保持板卡当前写合并服务及 150 MHz bitstream，无需重烧录或切换 PS 服务。

当前输入是已有 TT 录像，按原始时间戳约 30 FPS 实时送帧；这不同于读取历史 .orbv 回放，也不表示已连接摄像头或无人机直播。录像结束后显示最后一帧，重新运行入口可从头开始。窗口关闭时入口清理它自己启动的 WSL 会话。

```powershell
.\orb60\viewer\run_wsl_live.ps1
# 有限长度验证；默认0为完整序列
.\orb60\viewer\run_wsl_live.ps1 -Frames 600 -Seconds 28
```

使用既有 Ubuntu-20.04 的 ORB-SLAM3 安装。源码头文件的刷新率更新由 `prepare_wsl.py` 增量编译，保存原头文件、ELF、共享库及 SHA；本机已完成，不要在运行中重编译。

卡顿修复包括：遥测采样上限可配置至 60 Hz，GUI 使用 16 ms 精确计时器；完整地图仍约 2 Hz，点云颜色和关键帧几何只在变化时重算；实时模式等待对应彩色源帧就绪后一起显示，不在灰度和彩色之间闪换；同一源帧的重复请求不再从 MP4 开头重新解码。Windows 计时采用高分辨率 QueryPerformanceCounter，避免本机 CPython 3.12 的 GetTickCount64（15.625 ms）影响短间隔统计和调度。

WSL 的有节奏输入默认启用 120 ms 显示缓冲，最多 8 个快照，吸收短时送帧抖动；这会增加约 120 ms 显示延迟。需要更低延迟可用 `-BufferMs 0`，恢复单个可替换快照。该缓冲不用于无节奏的极限吞吐测试，不修改后端输入顺序、队列或特征。

900 帧实体直连验证：约 29.48 FPS（按输入节奏限速），885 个显示快照，约 29.49 快照/输入秒；全部特征记录 CRC、数量及顺序与保留结果一致，CPU ORB 调用为 0。证据在 `orb60/build/viewer/20261021/wsl_live900/acceptance.json`。这不是极限吞吐测试，不能把限速后的 29.48 FPS 与写合并版本的 56.91 FPS 混为一谈。

最终 600 帧一键入口验证：SLAM 约 29.43 FPS，窗口实际约 29.08 FPS，收到并显示 586 个快照，无显示队列溢出；窗口更新 CPU 耗时 P99 约 14.83 ms。显示间隔 P99 仍约 101.70 ms、最大约 126.26 ms，所以这是接近 30 FPS 的实时显示，不是无抖动锁定 30 FPS。CRC、点数、时间戳和顺序再次一致。详见 `orb60/build/viewer/wsl_live_20261021_141457_775/acceptance.json`。

## 打开

在本机双击项目根目录的 `Launch-ORB-Viewer.cmd`。本机配置位于忽略的 `orb60/build/local/viewer.json`；当前默认打开已验证的真实录像与地图，不会启动 FPGA 实验。配置路径相对于该 JSON 文件，可参考 `local.example.json`。

手动打开已有记录：

```powershell
.\orb60\viewer\run.ps1 -Recording .\orb60\build\viewer\20261021\slam_full\telemetry -Video .\recordings\tt\flight_20261004T184929_998838_6bb93c56\video.mp4
```

首次安装依赖使用项目环境：

```powershell
. .\scripts\project_env.ps1
uv pip install --python $ProjectPython -r .\orb60\viewer\requirements.txt
```

界面左侧是处理速度、特征数和图层开关；中间是原图与灰度特征；右侧是稀疏地图、相机轨迹、关键帧和当前相机。左键旋转，中键平移，滚轮缩放，F 适配地图。可跟随相机、暂停、拖动回放、切换速度，导出 PLY 点云或保存截图、轨迹 CSV 与原始快照。

绿色特征表示该帧关联到有效地图点，金色表示未关联。三维点来自真实 SLAM 地图，并非把二维特征假设为三维点。单目地图使用相对尺度，现有相机参数仍为临时借用值，因此这里不宣称米制定位精度或稠密表面重建。

## 原图同步与帧率

网口输入当前是灰度图。彩色原图可从同一序列的本地 MP4 解码，必须有 `source_frames.csv` 中的 `timestamp_ns -> source_frame_index` 映射；找不到映射时显示灰度图并提示原因。当前原片有 24 帧前导，不能直接用 SLAM 帧号索引 MP4。程序自动查找记录目录或其父目录中的映射，也支持 `-FrameMap`。

左侧 FPS 来自 SLAM 遥测中的最近采样窗口，底部另显示最近 3 秒的界面更新 FPS，两者不同。新版实时图像默认上限 30 Hz，可通过 `run_slam_network.py --telemetry-fps` 配置为 1..60；WSL 实时入口使用上限 60 Hz，地图仍约 2 Hz。WSL 已重编译此更新，旧 RK 二进制需要另行重编译才会采用新采样配置；本轮未覆盖它。历史 .orbv 记录只有约 10 Hz，换入口不会给旧记录补造新帧。显示采样不改变送入 FPGA/SLAM 的帧数。DDR 写合并版本已保留的整段吞吐结果为约 56.91 FPS，历史回放中的 FPS 不能用于重新评价它。没有把 57 写成界面常量。

## 连接鲁班猫

鲁班猫只需要 Python 标准库桥接，不需要 Qt。桥接读取 SLAM 原子写出的 `latest.orbv`，慢客户端不阻塞 SLAM。最多 3 个客户端，单个客户端发送超时 2 秒。两端均只监听本机，经过已有 SSH 密钥隧道连接。

先通过现有 RK 工作流启动桥接，目录必须指向准备显示的那次运行：

```powershell
.\rk3588\orbslam3_cpu_baseline\scripts\rk.ps1 start 'python3 runtime/orb60_viewer_20261021/sources/orb60/viewer/bridge.py --directory runtime/orb60_viewer_20261021/slam_full/telemetry --bind 127.0.0.1 --port 8765' -Name orb-viewer
```

本次已启动的同端口桥接可以复用，不要重复启动。然后：

```powershell
.\orb60\viewer\connect.ps1 -Video .\recordings\tt\flight_20261004T184929_998838_6bb93c56\video.mp4 -FrameMap .\orb60\build\viewer\20261021\slam_full\source_frames.csv
```

`connect.ps1` 自动建立 `127.0.0.1:18765 -> RK 127.0.0.1:8765` 隧道，界面退出后清理它自己启动的隧道。已有本机端口可复用。若数据源已结束，连接只显示最后一帧并明确标为“处理已完成”；连接本身不会重新播放视频或启动 SLAM。持续更新需要 SLAM 正在往该目录写入。

新运行使用现有 `orb60/scripts/run_slam_network.py` 加 `--telemetry` 或 `--telemetry-record`，其余数据集、相机、接口和 `fpga-pipeline` 参数保持现有工作流。`--telemetry` 仅保留最新包；`--telemetry-record` 还保留显示快照用于回放。用户给定最新 PS 写合并服务继续使用，不要运行旧版服务安装脚本覆盖它。

## C++ 接入与边界

在已经应用 0016 / 0017 / 0018 的 ORB-SLAM3 上，通过 `orb60/scripts/install_slam_telemetry.py --source <ORB_SLAM3> --workspace <project>` 安装 `0019-slam-visualization-telemetry.patch` 和 `OrbTelemetry.h`，然后使用原有编译入口。仅新增只读快照接口及异步写出，不改变特征选择、描述子、匹配或优化算法。C++14 下 Eigen 对齐声明及 aligned_allocator 是必要部分，不能删掉。

地图更新锁采用 try_lock；正在优化时跳过该次全图采集。编码线程仅有一个待处理快照，可替换旧显示帧；网络和 GUI 也有有界缓存。ORB 帧号与采样时间戳贯穿显示链路。线格式 `ORBVIZ01` 包含 JSON 元数据、显示 JPEG、地图点 ID/XYZ、关键帧 ID/Twc 和 CRC32。原始灰度 CRC 与实际输入对应；JPEG 仅供显示。地图最多 20,000 点、2,000 关键帧，GUI 轨迹最多 5,000 个采样位姿；导出保留 SLAM 原坐标，显示采用 X/Z/−Y。

本次安装前的原二进制、库及三个被修改文件在鲁班猫 `runtime/orb60_viewer_20261021/pipeline_snapshot/`，有 SHA256 清单。该备份用于本次可视化改动回退，不是最新 PS 服务的替代品。

## 已验证

- 实体 FPGA + 鲁班猫完整 2,273 帧，CPU ORB 调用为 0；帧序、点数、64 字节特征记录 CRC 与保留的同输入结果全部一致。
- 451 个真实显示快照，421 个有效采样位姿，最多 2,839 地图点、145 关键帧；位姿有限、旋转正交、点 ID 唯一。
- SSH 实时连接收到 149 个递增快照，验证连续更新、实际 FPGA 点数及地图内容。
- 桌面实际操作验收覆盖图层、播放/暂停、前后跳转、初始化前隐藏相机、逐像素原片映射，以及截图 / PLY / 轨迹导出。
- 协议单元测试覆盖截断、CRC、长度边界、分片 TCP、地图切换、失效位姿和桥接。

证据在 `orb60/build/viewer/20261021/visualization_acceptance.json`、`live_changing_acceptance.json` 和 `gui_verified/desktop_acceptance.json`。完整录像在 `slam_full/telemetry/frames/`。历史完整运行约 45.22 FPS，仅说明当次集成成功；最新 57 FPS 写合并版本未在此重新测速。

本次首次长回放发现 RK 上两个 PNG 的缓存读内容与数据集 SHA 不符，驱逐干净文件缓存后重读恢复，随后完整回放成功；失败记录保留。这不证明 RK 内存稳定性已经解决。原 MP4 解码也可出现既有 H.264 错误提示；灰度输入及 FPGA 特征一致性独立验收，不以彩色预览代替它。

复核命令：

```powershell
. .\scripts\project_env.ps1
& $ProjectPython .\orb60\viewer\test_viewer.py
& $ProjectPython .\orb60\viewer\verify_recording.py --run .\orb60\build\viewer\20261021\slam_full --reference .\orb60\build\linux\frame_pipeline_20261021\slam_pipeline2273 --live .\orb60\build\viewer\20261021\live_changing_acceptance.json --output .\orb60\build\viewer\20261021\visualization_acceptance.json
& $ProjectPython .\orb60\viewer\qa_desktop.py --run .\orb60\build\viewer\20261021\slam_full --video .\recordings\tt\flight_20261004T184929_998838_6bb93c56\video.mp4 --output .\orb60\build\viewer\20261021\gui_verified
```
