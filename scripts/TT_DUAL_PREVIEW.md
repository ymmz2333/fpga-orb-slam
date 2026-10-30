# TT：电脑 / RK3588 双窗口实时预览

## 直接运行

```powershell
powershell -ExecutionPolicy Bypass -File D:\pld\scripts\run_tt_dual_preview.ps1
```

前提：电脑与 RK 接实验路由器，TT 已加入该路由器；`ssh rk3588` 免密连接正常。
先关闭手机 Tello App、Xbox 控制站及其他 TT 预览程序，避免控制/视频端口竞争。
这个程序只预览和录制，不发送起飞、RC、启动/停止电机或降落指令。
`-CaptureKind flight` 只改录制分类，不启用飞行控制。

- 左窗口：电脑 PyAV / D3D11VA H.264 硬解（当前 AMD Radeon 780M 已验证）。
- 右窗口：RK3588 `mppvideodec` H.264 硬解后，回传电脑显示。
- 默认：4 档、high 分辨率（此 TT 实测 960×720）、high 帧率（请求 30 fps）。
- 点击左侧电脑窗口后，R 开始/停止录制，S 保存电脑原帧，Esc/Q 关闭并关流。
- 录制保存 TT 原始 H.264，不保存 RK 回传 JPEG；完成后无重编码封装 MP4。
- 正常视频在 `D:\pld\recordings\tt\`；诊断在 `.work/tt-video-viewer/<会话>/`。

要比较电脑软解，只需：

```powershell
powershell -ExecutionPolicy Bypass -File D:\pld\scripts\run_tt_dual_preview.ps1 -Decoder software
```

## 数据链路和画质边界

只接收一次 TT 视频流。电脑解析后的同一批 H.264 包供本机解码，并经 SSH 二进制管道
送 RK 解码；不让两台接收端争抢 TT 的视频目的地址。
右窗口为原尺寸 JPEG 预览（quality=85），不是逐像素无损回传。它适合肉眼观察，
但严谨画质差异需要本地无损导出的同帧数据，不能把 JPEG 压缩差异归因于 H.264 硬解。
两窗口显示各自最新帧，可能有时间差，不是帧同步比较工具。

RK 预览默认软件 `jpegenc`，H.264 仍是 MPP 硬解。可显式试硬件 JPEG 路径：

```powershell
powershell -ExecutionPolicy Bypass -File D:\pld\scripts\run_tt_dual_preview.ps1 -RKPreviewEncoder mppjpegenc-copy
```

这条路径先将解码帧转为普通 I420 内存，再用 `mppjpegenc rc-mode=fixqp q-factor=85
zero-copy-pkt=false` 编码。已通过一次 300 帧、标称 30 fps 回放及 EOS 检查，未证明更快，
因此不是默认方案。直接 MPP 帧接入 JPEG 的候选多次 EOS 超时，重连后仍失败，未保留为用户入口。

窗口分开显示 RK **decode fps** 和 **preview fps**。前者在 JPEG 前统计，后者包含
编码与回传限制。SSH 回传问题不代表将来 RK 本地处理也存在相同限制。
`pc_packet_to_preview_ms` 是电脑解析包→RK→JPEG 回到电脑的时间，不是相机端到端延迟。
板上时钟未同步；不跨主机相减墙钟时间。批量平均 fps 包含启动/收尾，不作为瞬时视频 fps。

## 本次证据（2026-10-04）

- 实机短测：请求设置均获 `ok`，电脑 D3D11VA 硬解激活，PC 与 RK 各输出 303 帧，
  PC 无 FFmpeg 解码异常或 corrupt 标记。录制从关键帧预卷起保存 300 包、10 秒标称 MP4。
  会话 `.work/tt-video-viewer/20261004T145637_041206/`。
- 原始视频 `recordings/tt/handheld_20261004T145641_592239_0dac4563/video.mp4`，
  原始包和请求配置也保留。未飞行，测试结束 `streamoff` 获确认。
- 最终离线验证 `.work/tt-decode-compare/dual-preview-final-20261004/`：同一份 5 档录制，
  PC 软解与 D3D11VA 均 300 帧、无 corrupt 标记；RK 300/300，EOS 完成、SSH exit 0，
  30 fps 节奏回放时 decode≈30 fps、预览≈13 fps。
- PC 快速离线处理（含 BGR 下载/转换）软解≈97 fps、D3D11VA≈74 fps。
  本机硬解能工作，但不能声称它自动比软解更快；这也不能隔离旧 Wi-Fi 卡顿的根因。
- 硬件 JPEG 普通内存路径结果在 `rk-hw-jpeg-i420-paced-20261004/`，300 解码、115 预览、
  EOS 正常。直接帧路径失败结果保存在其他 `rk-hw-jpeg-*` 目录，没有改标通过。
- 无损本地抓帧试验 `runtime/tt_video/quality_local_20261004` 未通过完整 EOS，
  不作为同帧画质签核；最新用户范围是交付双窗口预览，未继续该诊断。

这些都是短测，不证明长时间稳定性、没有源流损坏或完整光子到光子延迟。
MPP 使用预览默认 `ignore-error=true`，输出帧数相等不代表每帧图像干净。

## 环境恢复与离线自检

RK 使用系统 Python + GI / GStreamer + 已有 Rockchip MPP 插件，不安装新系统软件。
若更换板子或修改 helper，先部署对应源码：

```powershell
scp D:\pld\scripts\tt_rk_decode.py rk3588:orbslam3_cpu_baseline/runtime/tt_video/tt_rk_decode.py
```

上述路径是当前板工程内的 media-only helper，SSH 主机/密钥仍在原生 SSH 本地配置。
软件选择为电脑/PS 软件控制 + 成熟 D3D11VA/MPP API，不修改 PL 或 Xbox 飞行策略。

```powershell
powershell -ExecutionPolicy Bypass -File D:\pld\scripts\run_tt_dual_preview.ps1 -SelfTest
. D:\pld\scripts\project_env.ps1
& $ProjectPython -m unittest discover -s D:\pld\scripts -p 'test_tt*.py' -q
```
