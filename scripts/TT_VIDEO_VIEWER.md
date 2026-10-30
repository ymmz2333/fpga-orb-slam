# TT 实时视频预览（电脑直连实验路由器）

实现选择：电脑/PS 软件，不使用 FPGA。网络接收与 H.264 解码在独立进程中，
GUI 通过单帧共享内存读取最新画面；不运行实时计时码识别，按 R 才保存连续视频。

2026-10-04最新设置：采集入口均默认 **4 档（请求 4 Mbps）、720P、30 fps**，
可用 `-Bitrate 0` 选择自动。`-Decoder d3d11va` 启用本机 AMD 硬解，拒绝静默软解回退。
电脑 / RK 双窗口的简化入口和验证边界见 [TT_DUAL_PREVIEW.md](TT_DUAL_PREVIEW.md)。
2026-10-04新增 Xbox **Y** 录制开关：一次按下开始，再按一次停止，长按不重复。
窗口不必在前台；启动/手柄重连时已按住 Y 须先释放。默认读取手柄 0，可用
`-ControllerIndex 0..3` 选择。此入口只读取 Y，不将扳机/摇杆映射成飞行指令。

## 飞行 / 手持视频采集（2026-10-04）

手持采集使用下面的只读入口，不包含飞行控制：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_tt_video_viewer.ps1 -CaptureKind handheld
```

飞行采集使用 Xbox 控制站，保持现有操控方式：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_tt_xbox.ps1 -Live -CaptureKind flight
```

两者**不要同时开**，它们需要相同的视频和控制端口。点击视频窗口使其获得焦点，
按 **R 开始**，再次按 **R 停止**；可在一次运行中分段录制，不限于 10 秒。
也可使用 Xbox **Y**；停止后等待录制收尾完成，再录下一段。
面板会显示 REC、分类、时长和接收进程确认后的 RECORDING 状态。
正常关闭窗口会收尾；飞行窗口原有的关闭降落逻辑保持不变。
等待出现 `MP4 saved` 或终端 `event: exported` 后再复制完整目录。

正常视频保存在项目根的 `recordings/tt/flight_<时间戳>_<唯一编号>/` 或
`recordings/tt/handheld_<时间戳>_<唯一编号>/`，不是临时 `.work` 目录。
会话 `status.json` 的 `video_recordings` 保存这些绝对路径。

- `video.mp4`：供播放/后续算法读取的原分辨率彩色视频，不含 GUI 状态栏；停止后
  独立后台进程将 H.264 封装为 MP4，**不重编码、不缩放、不插帧**。
- `packets.h264`、`codec_headers.h264`、`packets.jsonl`：保留原始编码包与关联信息。
- `frames.jsonl`：每个实时解码帧的电脑端完成时间及原始尺寸。
- `capture.json`：原始录制关闭状态、类别和统计；`playback.json`：MP4 生成信息。

MP4 按请求的**标称 30 fps**重建播放时间轴，不是相机采集时间。源流丢包或卡顿时，
播放时长可能短于真实采集时长；真实电脑端间隔应从 `frames.jsonl` 读取，不能只用
MP4 帧号 / 30 做 SLAM 时间真值。保留上一关键帧开始的有限预卷，因此文件开头可能
包含按 R 前的少量画面；这些包没有按 R 后的实时解码时间，不能伪造为实时测量。
无关键帧、空录制或封装失败不会宣称 MP4 成功；原始包仍保留。
仅支持 TT 无 B 帧的低延迟流自动封装，发现 B 帧拒绝构造错误 PTS。

保存错误会单独提示，不新增飞行锁定或自动降落；源流本身的丢包不能由录制器补回。
不要强杀进程或在 `STOPPING` 时断电，否则可能没有完整关闭记录。
若原始录制已正常关闭但自动封装失败，可以查看 `export_error.json` 后手动重试：

```powershell
. .\scripts\project_env.ps1
& $ProjectPython .\scripts\tt_video_capture.py <录制目录>
```

离线回归，不连接无人机：

```powershell
. .\scripts\project_env.ps1
& $ProjectPython -m unittest discover -s scripts -p test_tt_video_capture.py -v
```

2026-10-04本次验证：12 项录制测试和 63 项既有遥控测试，共 75 项通过。
包含真实 H.264 编解码的 960×720 原尺寸保持、20 秒序列、GOP 中途开始后的逐帧
像素一致、重复录制、关闭收尾、磁盘异常隔离及后台封装；UDP 输入使用离线假 socket。
视频入口 SelfTest 和 Xbox 1 秒 headless 模拟入口通过，面板图已检查。
上述是录制功能初次离线验证；随后完成 5 Mbps 实机短时采集，见双窗口文档。
未进行本次飞行测试；实际 Wi-Fi 丢包和长时间录制仍须现场确认。

## 视频预览与延迟测试

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_tt_video_viewer.ps1
```

前提：TT 已开机并连接实验路由器；电脑在 `192.168.50.0/24` 局域网，外网可
独立走手机 USB。脚本不切换 Wi-Fi、不修改路由、代理、VPN 或防火墙。

2026-09-03用户通过路由器截图更正：TT（`RMTT-A45D1C`）地址为`192.168.50.24`，
此前的`.23`为误报。脚本默认使用`.24`，并在发送指令前验证ARP身份。
指定地址不代表设备必然在线，也不跳过MAC验证。可显式指定：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_tt_video_viewer.ps1 -DroneIP 192.168.50.24
```

- 当前请求视频设置：720P、4 Mbps（`setbitrate 4`）、30 fps；实际尺寸和解码交付帧率显示
  在窗口。`-Bitrate 0` 可改为自动；请求码率不代表实测吞吐，也不能保证不会丢包或卡顿。
- Esc/Q 或关闭窗口：请求关流并退出。关流是否收到确认保存在会话记录中。
- S：保存未叠加状态栏的原始彩色帧。
- **R：不限时长的普通视频录制开关**。**空格：手动开始 10 秒延迟录制**（不与普通
  录制同时运行）。弹出黑白计时图案后，把镜头对准图案，
  保持四角可见；10 秒后自动保存并回到普通预览。R 可提前结束。
- **Xbox Y：普通视频录制开关**，与 R 相同；延迟录制正在进行时可结束该录制。
- 录制保存编码视频包、真实解码完成时间及屏幕图案提交时间，不进行在线识别。
  保留上一个关键帧起的有限内存预卷，便于在 GOP 中途开始录制后准确回放。
  合成 packet PTS 只用于帧关联，不冒充相机的采集时间戳。
- 显示电池电量、主板最低/最高温度；不把 85 C 当作未经证实的官方关机阈值。
  台架长时间开机请保持通风，可用外部风扇；不要用启动电机的方式散热。
- 无电机启动、解锁、起飞、降落、RC 或紧急停机功能，精确命令白名单拒绝这些
  指令；仅有 SDK 握手、视频设置、开/关流、只读电池查询。
- 解码 FPS 不是相机源端实测 FPS；本程序不声称测得端到端视频延迟。

依赖为项目 `.venv` 中的 NumPy、OpenCV 和 PyAV（本次安装 PyAV 18.1.0）。
启动入口读取 `scripts/project_env.ps1`，不依赖固定用户目录。

每次运行的状态与预览图保存在 `.work/tt-video-viewer/<时间戳>/`。
`status.json` 包含实际命令、回复、解码计数、温度、电量及退出状态；`preview.png`
是达到 15 个解码帧后的首张自动留档图。启动失败不能当作实时预览通过。

不连接无人机的自检：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_tt_video_viewer.ps1 -SelfTest
```

当前已通过命令白名单、单帧共享内存往返与 Python 编译检查。首次 ARP 失败后
重新确认无人机在 `.20`，实机预览已经启动：会话 `20260903T183358_078223`
初次状态为约 30.31 解码 fps，960×720，89 帧，未记录解码错误。
离线录制器测试在编码流第 10 包开始录制，利用第 1 包开始的关键帧预卷，
52 个带标签帧均与原解码灰度图 SHA-256 一致。这是回放关联测试，不是延迟实测。
上述首个实机预览会话采用自动码率；随后按用户要求将启动默认值改为
`setbitrate 5`，完成实测后又按用户要求改为 `setbitrate 4`；
2026-09-03按最新要求将视频预览和手柄控制站统一改回 `setbitrate 0`（自动）。
2026-10-04按最新要求再次统一改为 `setbitrate 5`，以上旧日期设置仅为历史记录。
同日用户反馈偶发绿条/坏帧后，最新默认重新改为 `setbitrate 4` 进行观察。
该参数修改不证明坏帧来源；应使用同一段原始录制比较软/硬解，并检查码流错误与接收情况。
现有进程不会热更新，需要关闭窗口后重新运行。

完成录制后再分析（不要在采集期间运行分析）：

```powershell
. .\scripts\project_env.ps1
& $ProjectPython .\scripts\analyze_tt_latency.py <录制目录>
```

录制目录位于会话下的 `latency_<时间戳>/`，也会记入 `status.json` 的
`last_recording`。分析器只接受已关闭的录制；输出 `analysis.json` 和少量证据图。
结果定义为“源屏幕软件提交图案→电脑 BGR 帧可用”，包含源屏幕提交/刷新开销与
约 50 ms 图案驻留的采样不确定性，不包含接收屏幕扫描显示，不是光子到光子延迟。
