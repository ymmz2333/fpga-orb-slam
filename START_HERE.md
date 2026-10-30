# 新会话从这里开始

项目根目录已经迁移到 `D:\pld`。旧目录只作为回退副本，不再继续开发。

## 第一次进入或环境变化后

```powershell
cd D:\pld
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -RequireAmd -RequireModelSim
. .\scripts\project_env.ps1
```

只检查开源快速层时可以省略两个 `Require` 参数：

```powershell
.\scripts\check_environment.ps1
```

如果工具安装位置改变，复制
`scripts\local_env.example.ps1` 为 `scripts\local_env.ps1`，只改本机路径。
不要把本机绝对路径写回算法或构建脚本。

## 新会话必须先读

1. `AGENTS.md`：不可跳过的架构、验证和环境规则。
2. `panorama\WORKFLOW.md`：已经完成的门禁、指标和权威结果。
3. `DEVELOPMENT_GUIDE.md`：每种工具怎么用、常见故障和命令入口。
4. `PROJECT_TECHNICAL_PLAN.md`：TT + RK3588 + Zynq 的比赛系统架构、ToF
   尺度方案、视频质量策略和阶段验收指标。

## 三个最常用入口

```powershell
# 小型RTL/cocotb回归
.\.venv\Scripts\python.exe .\run.py --test fast9_nms_pipeline

# 14帧完整PS/PL软件仿真与全景图
.\panorama\run_multi_ip_batch.ps1

# XC7Z020完整顶层100 MHz布局布线
.\panorama\vivado_multi_ip\run_build.ps1 -FrequencyMHz 100
```

不要默认每次都跑14帧穷举或Vivado实现。日常使用小图和单元测试，只有接口、
算法输出或里程碑发生变化时才执行完整回归。

## TT实机输入与控制（与PL仿真独立）

- `scripts/TT_VIDEO_VIEWER.md`：只读视频预览、R 键不限时长真实视频录制、空格延迟测试；无飞行控制。
  Xbox Y 也可开始/停止录制，单次按下触发，后台可用；启动/重连按住须先释放。
  普通视频在 `recordings/tt/`，按 flight/handheld 分类；停止后无重编码封装 MP4，保留原包与时间侧车。
- `scripts/TT_DUAL_PREVIEW.md`：电脑 D3D11VA 与 RK3588 MPP 双窗口解码预览；
  入口 `scripts/run_tt_dual_preview.ps1`。当前视频默认 4 档、720P、30 fps；
  RK 回传 JPEG 只用于预览，预览 fps 不等于硬解 fps，不用于严谨像素画质对比。
- `scripts/TT_XBOX_CONTROLLER.md`：Xbox控制站；默认不联网模拟，`-Live`才连接实机。
  当前版本 tt-quorum3-linear30-stop1-delay2-20261004：LT+RT长按起飞、LB+RB降落；H悬停、U恢复、L降落。
  Xbox Y / 键盘 R 切换录制，不修改起降或杆量逻辑；PC 硬解用 `-Decoder d3d11va`。
  起飞按用户要求采用3/5不同副本成功确认，不足三条等待12秒后请求降落；不因视频/失焦另行降落。
  前后左右为线性曲线，四轴默认满杆30，保留15%死区；全部回中立即零RC，持续2秒后仅发一条stop。
  任一轴新推杆取消计时并立即恢复；持续回中不重复stop。H立即单包，不等应答，不使用F键，不加反向制动。
  -CenterStopDelay 3可改为3秒；-NoCenterBrake仅关闭自动回中stop，保留零RC与H。
  当前107项TT离线测试通过（含4档码率默认一致性）；quorum与延时触发有意不同于SDK默认策略，新配置尚未实飞校准。

## 当前签核基线

- 14帧：17,763个FAST/NMS候选、3,454个描述子和11,062,150次Hamming比较均
  有bit/byte精确验证。
- 最终全景图由模拟PL输出驱动，PS端完成RANSAC/Homography/Warp/Blend。
- 100 MHz：WNS `+1.914 ns`、WHS `+0.036 ns`。
- 125 MHz：WNS `+0.460 ns`、WHS `+0.036 ns`。
- 完整顶层约15.7k LUT、16.9k FF、14 RAMB36 + 5 RAMB18、15 DSP。
