# TT 视频解码与地面命令检查：官方依据核对

后续更新：本文件记录“只改自动码率”那一轮的历史状态。用户随后要求按 TT
官方源码对齐，GroundLink 和额外飞行门禁已移除；当前控制行为以
TT_SDK_CONTROL_REVIEW.md、TT_XBOX_CONTROLLER.md 为准。下面的视频分析仍适用，
“本轮未改门禁”等表述不应解读为最新控制版本的状态。

日期：2026-09-03。实现选择：电脑/PS 软件诊断。
本轮未连接无人机，未发送 SDK、飞行或电机指令；没有修改连接门禁、飞行状态机或解码循环。
仅将两个入口的码率默认值改为自动，增加离线码流检查脚本及回归测试。

## 官方源码范围

固定 DJI RoboMaster-SDK 提交 `ff6646e115ab125af3207a4ed3df42cc76c795b2`，
核对 TT 对应的 `Drone/TelloCamera/TextClient`，不把 EP 的 `Robot/EPCamera` 混进来。

官方视频启动需要 SDK 握手与 `streamon`，接收端使用 UDP 11111。
`setfps high` 为 30 fps，`setresolution high` 为 720P 档，`setbitrate 0` 为自动。
本项目新启动的控制站和纯视频入口统一使用这三个设置；IP 仍为 `192.168.50.24`，保留 MAC 核验。
这只是启动配置已修改，不是设备本轮已接收配置的声明。
依据：[TT SDK 3.0 手册](https://dl.djicdn.com/downloads/RoboMaster%20TT/Tello_SDK_3.0_User_Guide_en.pdf)。

注意官方材料存在不一致：该提交的 `16_video_stream.py` 示例使用码率 6，
但上述 SDK 3.0 手册列出的范围是 0–5。此次采用无此歧义的 0；不据示例中的 6
擅自推定本机固件接受范围或码率含义。
依据：[官方视频示例](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/examples/12_drone/16_video_stream.py)。

## 解码方式是否正确

基本处理路线有直接依据，但不能把它扩大成“整个实时视频程序已经验证正确”。

- 官方原生 `H264Decoder` 创建 FFmpeg H.264 解析器，使用 `av_parser_parse2`
  提取编码包，再用旧版 `avcodec_decode_video2` 解码；转换输出默认为 BGR。
  它不是把一个 UDP 数据报当成一张独立图片，也没有在该调用链中按固定数据报长度判定完整图像。
  依据：[media_codec.h](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/lib/libmedia_codec/src/media_codec.h)、
  [绑定默认参数](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/lib/libmedia_codec/src/media_codec.cpp)。
- 本项目 `CodecContext.parse(data)` 同样调用 `av_parser_parse2`，在多次输入间保存不完整包；
  `codec.decode(packet)` 经新版 FFmpeg send/receive API 解码，`to_ndarray('bgr24')` 转换输出。
  PyAV 18.1.0 的本地安装源码也已核对，不是只凭函数名判断。
  依据：[PyAV parse/decode 文档](https://pyav.basswood.io/docs/stable/api/codec.html)。

双方使用相同类型的解析/解码流程，不等于库版本、容错、延迟、像素结果或生命周期完全相同。
本轮未编译、运行 DJI 的原生解码器进行独立 A/B 对比。

## 实时实现的差别与缺口

1. 官方 `StreamConnection` 用独立收包线程和队列，`LiveView` 另有解码线程；
   本项目在同一接收进程的同一循环中处理视频收包、H.264 解码、BGR 转换和遥测。
   解码/转换/锁等待可能延迟下一次收包；这是待测风险，不是已经证明的卡顿根因。
   官方原始队列为 32 项、解码帧队列为 64 项，不应直接照搬这些大小作为低延迟方案。
   依据：[conn.py](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/conn.py)、
   [media.py](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/media.py)。
2. 本项目 `decode_errors` 和累计视频字节数只在成功发布一帧时写进共享状态。
   连续解码失败时，这两个可见计数也会停止更新，不能据它们区分“没收到视频包”和“包有但解不出帧”。
   Xbox 状态文件还没有分别持久化这两阶段的诊断信息。
3. 本项目没有视频会话断流后重新开流、重建解析器/解码器的恢复状态机。
   用户确认期间曾重启或换电，这与“遥测后来恢复、旧视频停留超过 157 秒”的记录相符，
   但不能因此解释重启前的所有间歇卡顿。
4. `video_age` 是距最后一张解码完成帧的时间，不是相机曝光到显示的延迟。
   只保存最新解码帧不代表 UDP 压缩字节缓冲没有积压。
5. 本轮所读的官方上述路径也没有完整自动重连状态机；不能宣称换用完整 SDK 就必然修复断流。

对应本地位置：`tt_video_viewer.py::receive_video`、`tt_xbox_station.py::control_worker/main`。
后续应先独立记录视频数据报计数/最后收包时间、解析包计数、解码错误/耗时、
最后成功帧时间和缓冲积压，再针对证据决定拆分收包与解码、丢失后的恢复策略。
压缩流溢出时不能随意丢弃数据报后假装参考帧仍完整。

## 已完成的离线分块检查

脚本：`scripts/check_tt_decoder_chunks.py`，不使用网络。
输入为已经结束的录制：
`.work/tt-video-viewer/20260903T183840_760334/latency_184034_017171/packets.h264`。

- 输入大小：5,334,075 字节。
- SHA-256：`9f427c4bccb9629f3274f1eb73d29b3b59f3b23a5457d77b4d7b943674657502`。
- PyAV 18.1.0，libavcodec 62.28.102。
- 同一后端通过 `av.open(..., format='h264')` 得到基线：320 帧，960×720。

| 重新分块方式 | 块数 | 最终帧数 | BGR 每帧哈希序列与基线一致 | decode 调用 p99 |
|---|---:|---:|---|---:|
| 1024 字节 | 5,210 | 320 | 是 | 5.527 ms |
| 1460 字节 | 3,654 | 320 | 是 | 4.910 ms |
| 4096 字节 | 1,303 | 320 | 是 | 5.224 ms |
| 固定随机种子，1–2000 字节 | 5,342 | 320 | 是 | 4.765 ms |

每种情况在文件结束前输出 319 帧，结束时冲刷解析器/解码器后得到第 320 帧。
这里的 flush 只适用于已经结束的文件，不应对每个实时 UDP 包执行。

这项测试证明该完整输入上的分块不变性；不同大小只是测试分块，不代表原始 TT UDP 包长。
它使用同一个 FFmpeg 后端，不是独立解码器正确性证明，不含原始 UDP 丢包、乱序、到达时间，
也不证明实时控制/视频延迟已通过。表中耗时只含 decode 调用，不含 BGR 转换、哈希、网络或显示。

```powershell
.\.venv\Scripts\python.exe scripts/check_tt_decoder_chunks.py .work/tt-video-viewer/20260903T183840_760334/latency_184034_017171/packets.h264
```

## 官方是否有“每五秒 command，无应答就锁住起飞”

**没有在本次核对的 TT 初始化、起降、RC 和视频示例中看到这套周期性地面锁定策略。**

- `05_takeoff_land.py` 初始化 Drone 后，调用起飞并等待完成，再降落并等待完成。
  依据：[官方起降示例](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/examples/12_drone/05_takeoff_land.py)。
- `Drone.initialize()` 最后发送 `command` 进入 SDK；STA 搜索设备时也会发送该命令，
  并提供显式 `send_command()` 方法。没有对应本项目的 5 秒周期/3 秒回复/7.5 秒有效期门禁。
  文件中另一个 `Robot` 类有 EP 心跳，不能当作 TT 的同一实现。
  依据：[robot.py](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/robot.py)。
- 官方 `TextClient.send_sync_msg` 默认单次等待上限为 10 秒；同步等待超时与持续地面解锁门禁
  是不同概念，不能直接把 10 秒抄成本项目新的通用超时。
  依据：[client.py](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/client.py)。

当前本地 `GroundLink` 的周期、回复期限和 `command_ready` 地面门控是我们添加的策略，
不是 SDK 官方要求。此前日志可确认它直接阻止了起飞指令的发送；
仍不能确定重复 `command` 无回复是固件行为、网络、会话竞争还是其他问题。

不能把“官方没有这个门禁”等同于“没收到命令应答也能安全起飞”。建议后续重新设计
明确、可关联、能恢复的连接确认过程；可在用户主动启用时完成有界校验，
区分初始握手、命令通道可用性和实际动作应答，而不是简单删除保护或无限延长有效期。
这是待实施方案，本轮没有修改 `GroundLink` 或飞行门控。

## 自动码率修改的回归

已修改 `tt_video_viewer.py` 的白名单/启动设置、`tt_controller_core.py` 的 SETUP，
以及对应使用说明。新入口使用 `setbitrate 0`，720P 和 30 fps 保持不变。

本次控制端 47 项离线/假 UDP 测试通过（包含新码率断言）；视频白名单/共享内存自检通过。
没有实机下发设置，没有运行官方示例中的起飞代码；不得据此宣称起飞锁定或实时卡顿已修复。
