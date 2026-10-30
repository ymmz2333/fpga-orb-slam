# Tello 手机控制器 APK 静态分析

分析日期：2026-09-03。对象：用户提供的 `base.apk.1`。

## 结论与边界

已定位到起降界面、摇杆、命令发送管理器、发送队列、UDP 收发、心跳和飞行状态模型。
但是，这个 APK 使用了应用加固：关键方法在随包 DEX 中只剩立即返回的占位指令，
不能由这些反编译产物还原真实的起降命令、摇杆数值转换、发送周期或重试策略。

因此，本报告是有原始字节证据的**部分结构分析**，不是完整协议还原，
也不是已复现官方 App 控制效果的声明。

本轮只在电脑上解析文件：未安装或运行 APK，未执行其中的原生库，未连接无人机，
未发送任何无人机命令。未修改 APK 或现有 Xbox 控制程序。实现选择为电脑/PS
诊断软件，不涉及 FPGA/HLS/RTL。

## 样本与可复现产物

| 项目 | 实测值 |
|---|---|
| APK 大小 | 31,618,407 字节 |
| APK SHA-256 | `b55f2e62cd4dff960e855a549c978f611f82683e86134a4bc9f2092b3703a8af` |
| Manifest 包名 | `com.ryzerobotics.tello` |
| 版本 | `1.6.8.0` / versionCode `160800` |
| Android SDK | minSdk 18 / targetSdk 30 |
| ZIP 条目 | 1,191 |
| DEX | 一个 `classes.dex`，7,067,956 字节 |
| DEX SHA-256 | `7d94f86880d0cd59e1ea371792d78e9469df0d1bc060543a7871719d56b0ea21` |

嵌入的签名证书 Subject/Issuer 均为 `CN=tello`，证书 SHA-256 为
`53:C7:8B:9D:02:5B:16:62:05:69:DD:06:D1:7F:D4:92:46:74:9F:9F:E8:EB:47:F6:47:2B:BC:81:9B:A1:F8:78`。
Java jarsigner 的 JAR/v1 签名检查返回 `jar verified`，同时提示自签名、证书链不受信任等。
这只是该签名方案下的文件一致性检查；未与厂商公布的可信指纹比对，
不等于独立确认发行来源，也不代表已验证所有 Android APK 签名方案。

产物目录为 `D:\pld\.work\tt-apk\b55f2e62`：

- `jadx\resources\AndroidManifest.xml`：解码后的 Manifest。
- `jadx\sources`：反编译结果；含大量空方法和错误，不可直接视作可运行源码。
- `classes.dex`：用于独立核对原始指令。
- `dex_audit_v2.json`：本次保留的逐方法审计；旧版 `dex_audit.json` 未删除。

只读分析脚本为 `D:\pld\scripts\inspect_tt_apk.py`，只依赖 Python 标准库。
在项目根目录运行，输入 APK 路径由调用者提供，输出必须使用尚不存在的文件名：

```powershell
$apkPath = Read-Host 'APK 的完整路径'
.\.venv\Scripts\python.exe scripts\inspect_tt_apk.py $apkPath --output .work\tt-apk\audit-new.json
```

该脚本是针对样本的结构/字节模式诊断，不是通用完整 Dalvik 反汇编器，
不是恶意软件检测器，也没有飞行控制能力。

反编译工具为官方 JADX 1.5.6，ZIP SHA-256
`545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974`，
与 GitHub 发布资产摘要一致。此次 JADX 返回退出码 1、报告 1,350 个错误；
不能标成“完整反编译通过”。工具出处：[JADX 官方仓库](https://github.com/skylot/jadx)。

## 可定位的控制结构

以下路径均相对 `jadx\sources\com\ryzerobotics\tello`。
类名、字段、类型引用提供结构线索；由于方法体缺失，**不能把下表当成已经恢复的运行调用链**。

| 部分 | 静态证据 | 能确认什么 / 不能确认什么 |
|---|---|---|
| 起降交互 | `gcs/engine/flight/b.java`，保留源码名 `TakeOffAndFly.java`；引用降落弹窗等 | 能定位相关模块，不能知道按钮最终发送什么字节 |
| 屏幕摇杆 | `gcs/engine/flight/rocker/RockerView.java`，触摸处理与摇杆回调方法 | 能定位输入层，不能还原死区、曲线、正负号或输出范围 |
| 命令管理 | `gcs/core/cmd/ZOCmdSendManager.java` | 有四个 volatile 整数字段及四整数参数方法，但不能仅凭签名断言通道顺序或单位 |
| 缓冲与序号 | `ZOCmdStore`、`ZOByteArray`、`ZOAtomicShort` | 可见字节缓冲与 short 类结构，具体打包、序号递增和重发逻辑未恢复 |
| 发送调度 | `ZOCmdSendLoop`、`ZOSendQueue`、`ZOUdpSendTask` | 可见 Handler/Looper、LinkedBlockingQueue、DatagramSocket；不能确定周期与优先级 |
| 心跳 | `gcs/core/d.java`，保留源码名 `ZOHeartBeat.java` | 能确认存在心跳模块，周期和内容未知 |
| 接收与状态 | `ZOUdpReceiveTask`、`ZODroneCmdHandle`、`FlyControllerEntity` | 能看到数据结构，状态字段解码与动作完成判定未恢复 |

`gcs/ui/bean/SocketPacketEntity.java` 的字段完整可读：

```text
int cmdId
byte[] data
int pacType
short seqNum
int version
```

同时存在源码名为 CRC8、CRC16 的类。这支持“App 内有命令号、报文类型、序列号和
校验相关处理结构”的判断，**尚不能证明具体线上报文布局或 CRC 参数**。
尤其不能据此把 SDK 文本协议的端口、命令名、通道范围直接套到此 APK 的控制链路。

`FlyControllerEntity` 可见 `height`、`flyMode`、`droneHover`、
`electricalMachineryState`、`eMOpen`、`eMSky`、`eMgroud`、
`downVisualState`、`lightStrength` 等字段。字段名称提示 App 的状态模型
不仅有高度；但字段的数值含义、位定义，以及它们是否参与降落完成判断，仍未恢复。
不能把“存在这些字段”扩大成“已经知道官方怎样判断停桨”。

APK 包含 Gamesir 相关组件，但本次未恢复 Xbox 通道映射。
`libdreamDroneParser.so` 可见导出涉及 H.264 SPS 分辨率和 YUV 转换，
不能因为库名含 Drone 就认定它包含起降/摇杆协议。

## 为什么空方法不是官方真实逻辑

Manifest 的 Application 为 `s.h.e.l.l.S`，组件工厂为 `s.h.e.l.l.A`。
加载器 `S.java` / `N.java` 引用原生加载和真实 Application
`com.ryzerobotics.tello.common.base.MyApplication`。包内存在：

- `assets/ijiami.ajm`，667,978 字节。
- `assets/asr/common.jet`，9,781,778 字节，文件头不是标准明文 DEX。
- 多架构 `assets/ijm_lib/.../libexec.so`。
- `com.ijm.dataencryption.DETool` 相关加载引用。

这些与静态方法占位共同构成应用加固证据。未还原其解密算法、运行时恢复流程，
也未证明真实控制代码在上述哪一个资产的哪个位置。

独立解析原始 DEX 的 `gcs` 命名空间，得到 1,849 个带 code item 的方法：

| 原始指令模式 | 数量 |
|---|---:|
| 立即 return-void，其余指令字节为零 | 1,452 |
| 返回零或 null，其余指令字节为零 | 363 |
| 返回 wide zero，其余指令字节为零 | 9 |
| 其他模式 | 25 |

合计 1,824 / 1,849，即约 98.65% 命中上述占位模式。
这是所选命名空间内的统计，不是对整个 APK 所有方法的统计，
也不意味着剩余 25 个方法都是可用的控制逻辑。

原始样例（偏移为 `classes.dex` 内 code item 起始偏移）：

| 方法 | 偏移 | 指令前缀 | 解释 |
|---|---|---|---|
| `ZOCmdSendManager.a(IIII)V` | `0x5803d8` | `0e 00 00 00 ...` | 首条 return-void，后续为零 |
| `ZOHeartBeat.run()V` | `0x588090` | `0e 00 00 00 ...` | 同上 |
| `RockerView.onTouchEvent(...)Z` | `0x58ba1c` | `12 00 0f 00 00 00 ...` | 装载零后直接返回 |

操作码解释以 [Android 官方 Dalvik 指令文档](https://source.android.com/docs/core/runtime/dalvik-bytecode)
为依据。结论不依赖 JADX 把方法显示为空：原始指令本身就缺少所需逻辑。
换一个 Java 反编译器不等于能恢复未以明文保存在这些 code item 中的实现。

另有 1,781 个方法的 debug offset 超出文件范围；DEX 头部 Adler-32 核对一致，
SHA-1 核对不一致。这是本样本的结构审计结果，**不是 APK 签名验证结论或恶意性判断**。
DEX 头字段定义参见 [Android DEX 格式文档](https://source.android.com/docs/core/runtime/dex-format)。

## 对目前 Xbox 控制问题的意义

本节对应 APK 分析开始前的控制端及历史日志，不代表后续修复版本的状态。
分析期间，另一任务通知已获用户授权，正在负责控制端修复及离线验证；
本任务未参与修改这些文件，也未验证另一任务的修复结果。

要区分三个对象：手机 App 的内部实现、DJI 发布的 Python SDK、我们自己的控制程序。
使用官方文档里的命令，不意味着上层状态机和重试策略已经等同于官方 App。

1. **降落：**现有程序发送的文本 `land` 确实对应 DJI SDK 的自动降落动作；
   但我们的“约两秒再发一次裸 `land`”是项目自己的策略，不是此次从 APK 恢复的逻辑。
   DJI Python SDK 的 `land(retry=True)` 源码使用带 `Re` 标签的五次发送，
   `retry=False` 才直接发送裸命令。这也不能直接当作该手机 App 的实现，
   或未经验证就推断当前 TT 固件的去重语义。
   依据：[DJI RoboMaster SDK Flight 源码](https://github.com/dji-sdk/RoboMaster-SDK/blob/master/src/robomaster/flight.py#L216)。
2. **移动：**此前用户实测日志显示程序停留在 `HOVER`，未进入 `FLYING`，
   非零 RC 发送数为零。这个现象首先关联我们自己的权限门控，
   不能据此认定无人机不接受移动指令，也不需要靠猜 App 通道值来解释。
3. **状态误判：**此前已经定位到本地采样顺序可能产生很小的负遥测年龄，
   进而被误判为过期。此 APK 分析没有修改或验证修复该问题。
4. **落地回弹：**当前没有足够的同步画面、完整状态和可关联应答来确定原因。
   不应宣称是重复降落命令导致，也不能仅凭高度接近零断言已落地停桨。

对应历史记录为 `D:\pld\.work\tt-xbox\20260903T193131_652591`；
本轮没有重新实飞。以上控制程序问题的修复状态以后续修复任务的结果为准，
不能因为完成了 APK 分析就标为已修复或已通过实机验证。

## 下一步如何获得真实控制证据

当前未恢复的关键项：起降命令 ID/载荷、取消降落行为、摇杆数值和方向、死区/曲线、
持续发送频率、心跳周期、重发/应答关联、落地停桨状态判据。

优先考虑由用户选择并授权的实际通信采集，而不是把空方法补成猜测实现：

1. 先验证抓包位置确实能看到“手机 App ↔ TT”的双方报文。
   电脑与手机/TT 接同一路由器，**不代表电脑普通网卡能看到它们之间的单播通信**。
   手机侧采集、具备合适抓包能力的 AP/转发路径等方案需要另行核实；
   不默认 XDR3010 支持端口镜像，也不擅自更改网络拓扑。
2. 第一阶段只观察地面停桨时的连接、静置、断开，记录时间和连接模式，
   判断是否文本/二进制及心跳节奏。关闭其他控制器，避免争抢会话。
   此阶段不能验证真实飞行时的落地或摇杆语义。
3. 如随后需要起降/移动通信，必须由用户在受控场地另行确认并亲自操作，
   同步记录按键、画面和报文；不能为获取样本自动起飞。
4. 若需要恢复运行时方法而非只分析流量，需单独选择测试设备与调试方式。
   安装 APK、开启调试、修改手机环境或运行时解包不包含在本轮操作中。

最终应得到可对照的“输入动作—发送报文—应答—飞行状态变化”时间线，
再据证据修正 Xbox 控制站。未核实的私有协议不直接用于实机控制。
