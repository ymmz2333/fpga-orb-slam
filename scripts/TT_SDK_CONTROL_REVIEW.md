# TT 教育无人机 SDK 对齐与控制修复记录

## 2026-09-04 当前版本覆盖说明

当前实机版本为 tt-quorum3-centerbrake-20260904，使用 tt_quorum_actions.py。
下面2026-09-03的SDK FIFO、无限等待与线性杆量内容是历史记录，不再是当前运行合同。
tt_sdk_actions.py 仅保留为离线官方对照参考，控制站不导入它。

本次按用户明确要求：五副本中的三个不同编号成功就放行起飞，少于三个等待12秒后请求降落；
同一组内按副本编号去重，不混合不同组，已退休起飞组不能完成后续降落。
完全未识别起飞回复组时仍请求降落，但不把无法区分归属的后续回复伪造为降落确认。
stop 改为官方 retry=False 的裸命令，因此裸 ok 不参与编号 quorum。

回中原来已发送零RC，本次追加一次stop而非反向杆量；四轴回中后自动恢复新输入，
不进入必须按U的锁定。前后左右使用二次曲线，半杆约17、满杆100，升降和转向不变。
H/U不能绕过未完成的起飞3/5，也不能取消该等待截止时间。

验证：63项离线测试通过；官方当前发包方法12项比较通过；63项含历史参考测试，
不将旧FIFO对照包装成新策略与官方行为完全一致。报告为
.work/tt-sdk-reference/quorum3_wire_conformance.json。
原始失败会话20260903T232224_603145回放中，01/03/04/05在第三条回复时放行，
首条模拟RC距起飞5.900052秒。只读启动目录20260904T221507_624275，参数正确、无网络、无动作。
本轮未发送实机起降/移动/stop；制动距离、回中手感及缺包真实处理仍待人工验收。

## 2026-09-03 历史记录

日期：2026-09-03。当前版本：tt-sdk-text-fullrange-rollfix-20260903。
实现选择：电脑/PS 软件。用户明确要求按 TT 官方源码执行，删除此前自加的飞行门禁。
本轮不运行实机指令，不修改 FPGA 或视频解码路径。

## 设备与来源确认

官方仓库 dji-sdk/RoboMaster-SDK 同时有两个对象，不可混用：

| TT / Tello EDU | EP 地面机器人 |
|---|---|
| robot.py 的 Drone | robot.py 的 Robot |
| flight.py 的 Flight | chassis、gimbal 等 |
| TextClient / TextAction | 另一套二进制消息、心跳和动作 |
| examples/12_drone | 其他机器人示例目录 |

本项目对齐 TT 分支，不是把 EP 心跳套到无人机。
以下固定为提交 ff6646e115ab125af3207a4ed3df42cc76c795b2：

- [TT 起降示例](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/examples/12_drone/05_takeoff_land.py)
- [TT RC 示例](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/examples/12_drone/13_rc.py)
- [Flight 发包](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/flight.py)
- [TextAction / ActionDispatcher](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/action.py)
- [Drone 与 Robot](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/robot.py)
- [TextClient](https://github.com/dji-sdk/RoboMaster-SDK/blob/ff6646e115ab125af3207a4ed3df42cc76c795b2/src/robomaster/client.py)

## 前次起飞锁定的实机证据

来源：.work/tt-xbox/20260903T215831_855748/events.jsonl，旧版本由用户亲自操作。

| 起飞请求后 | 日志 |
|---|---|
| 0 秒 | Re8201..8205 takeoff |
| 8.899 秒 | Re0101..0105 ok，被旧代码列为 uncorrelated_reply |
| 10.002 秒 | 高度 90 cm、电量 77%、窗口前台、视频/遥测新鲜；程序主动发送 Re8301..8305 land |
| 14.399 秒 | Re0201..0205 ok，再次被拒绝 |

状态经过 READY -> TAKING_OFF -> LANDING，没有进入 FLYING，非零 RC 记录为零。
这证明本次自动降落由程序“起飞结果不确定”分支触发；
不能再把本次归因于摇杆幅度、低电量或无人机自行保护。
编号为何被改变，当前未还原固件机制；不能断言 01/02 是写死的命令 ID。

## 对齐实现

tt_sdk_actions.py 保留 Flight 默认的五副本格式与编号递增/回绕；
应答识别与分发按 TextAction/ActionDispatcher，而非发送标签原样回显。
最后一个副本对应官方方法返回的 action，因此仍等待该副本完成。
普通 ok 也接受，不将其自动当作无关回复。

这是一份对指定方法行为的本地适配，不是安装并运行整个官方 SDK。
Windows 指定网卡/端口绑定、XInput、视频显示和输入采样仍由项目程序负责。
未加载 EP 类、未执行官方带起飞的示例、未声称恢复手机 App 内部协议。

已移除 GroundLink、动作固定超时后自动降落、5 秒/高度/回中交接、
失焦/视频/遥测/GUI/循环延迟触发的自动悬停降落、电量门槛和单会话单次起飞限制。
仅保留明确的人机操作：组合键触发、H 悬停、U 恢复、L 降落及正常退出请求降落。
物理输入缺失时杆量为零；不额外启动定时降落。完整操作说明见 TT_XBOX_CONTROLLER.md。

官方默认等待没有超时；无应答时本地保持待完成，允许操作者请求 L。
正常退出最多等待降落完成 20 秒，此后报告未确认并退出，不追加飞行命令。
实际电量/失联行为仍由无人机固件处理，程序不绕过它们。

## 对官方行为局限的如实保留

官方的 Re 成功格式使用前缀匹配，ActionDispatcher 顺序消费待处理 TextAction，
不严格比较发送 ID，也不从收到的 ID 推断命令名。
因此它不是防重放/抗迟到的强事务协议。丢失起飞应答时，后来降落应答可能先被之前
未完成的 action 消费；本版不把这种情形包装成精确关联，也不根据高度伪造应答。
这与旧版“不接受任何不匹配 ID”的失败假设是两回事。

## 可复现验证

fetch_tt_sdk_reference.ps1 从官方固定提交下载两个源文件，校验 SHA-256。
check_tt_sdk_conformance.py 在验证哈希后仅抽取指定 AST 方法，
以全内存假动作/假传输运行官方方法，不执行包初始化、示例或任何网络操作：

- Flight.takeoff/land/stop/rc：60 组发包比较，含四轴正负端点、全轴满杆、零杆量。
- TextAction.found_action/_update_action_state：66 个成功、错误及格式边界样例。
- ActionDispatcher._on_recv：20 次实际分发方法比较，涵盖收到不同编号和动作并存。
- 输出 .work/tt-sdk-reference/conformance.json：PASS；real_flight_verified=false。

固定源码哈希：

    flight.py  7b7a37dd8077a808119c380e7c0ed47d9ea1d026deeebe8e5ee8f7534a5a71eb
    action.py  2b9ff3f26d4f28fd2b40e376740c4f799b93167c4572ed4a68a36deaf4c1fc39

run_tt_xbox.ps1 -SelfTest：41 项离线单元/假传输测试通过。
Python 编译检查通过。本轮未执行任何实机起飞、移动或降落。

旧版 47 项测试的部分目标是已被用户废止的门禁，不再作为新合同验收条件；
不是忽略旧失败或把旧验证改标通过。修改前源码、测试和说明均保存在：
.work/tt-control-before-sdk-alignment-20260903-221309。

仍待新版本人工验收：实际起飞应答后的摇杆接管、四轴方向/幅度、手动降落、
第二次起飞、视频/网络实际表现。离线对照不能证明真实飞控行为。

## 本次全范围与横移方向修正

用户已反馈操纵可以，但移动不明显，右杆左打时机体向右飞。
只读查看当时控制进程参数为 --rc-limit 15 --signs -1 1 1 1；
程序旧默认另为 +/-30，因此同时修正启动器、Python CLI、核心映射和面板默认，
避免只改其中一处仍被旧默认覆盖。

官方 Flight.rc() 文档为四通道各 [-100,100]，实际方法直接发 rc a b c d，
没有额外限幅或缩放。SDK 3.0 手册第 5 页同样列出此范围；speed x 的 cm/s
是另一条命令，不能当成 RC 杆量与真实速度的换算表。
[官方 SDK 3.0 手册](https://dl.djicdn.com/downloads/RoboMaster%20TT/Tello_SDK_3.0_User_Guide_en.pdf)。

按用户要求默认最大杆量设为 100；只将横移方向 -RX 改成 +RX，其余三轴保持不变。
15% 死区、20 Hz 发送节拍、起降和应答流程没有修改。
新增测试验证四轴端点、完整 16 位输入域的单调有界性、旧参数仍可显式覆盖，
并以假 UDP 验证右杆左/右满杆分别发 rc -100 0 0 0 / rc 100 0 0 0。
41 项测试和扩展后的官方源码对照均通过，Python 编译检查通过。

本轮未连接无人机，也没有停止、重启正在运行的控制进程。
变更只在重新启动程序后生效；操作者需先落地停桨，再关闭旧窗口并重开。
新的实际横移方向与全杆响应仍待人工验收，不把用户对旧版的反馈当成本版实飞通过。

当前启动器 3 秒 Headless 只读启动也已通过：.work/tt-xbox/20260903T230214_671062。
记录 limit=100、signs=[1,1,1,1]、pad.connected=true、real_network=false、actions={}。
仅说明当前参数实际生效且 XInput 可读，不证明实机运动方向或响应。
