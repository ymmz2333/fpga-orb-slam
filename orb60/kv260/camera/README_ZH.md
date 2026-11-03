# KV260 USB 3.0 摄像头入口

最新现场复测已完成：用户将摄像头对回建图区域后，真实2400帧输入获得2386帧有效位姿，第2帧首次定位，初始化后有效率99.50%；7015原生入口23.56 FPS，采集发送及排空范围23.65 FPS。CPU ORB为0、全部帧身份一致，333,261点彩色背景构建1次复用2399次，HDMI无欠载或AXI错误。位姿记录显示相对位置发生变化，未据此声称外部真值精度。证据在 `build/kv260_system/camera_relocalization_20261103_a/HOST_VERIFICATION.json`。

该复测证明已有摄像头地图的真实固定地图定位；早期1200帧建图的93.82%稳定性结果和未对准区域时的失败均保持原记录。用户随后确认可以进行两板单网线测试，当前仍待实际直连运行并接回路由器后读取日志，不能把准备通过记为物理直连通过。

2026-11-03，摄像头已从7015移到KV260。实际USB树为：xHCI 5000M → USB5734 5000M → `3.0 USB Camera` 5000M，设备为 `/dev/video0`；`/dev/video1`是同一UVC设备的其他节点，不另作第二台摄像头。

实际协商格式为 **1280×720、YUYV、60/1 FPS**，行跨度2560字节。60 FPS是驱动协商值，实际处理速度按时间戳和墙钟分别记录。驱动没有列出UYVY；UYVY的像素顺序只完成了软件测试。

PS使用Linux现有UVC/V4L2驱动和4个MMAP缓冲。`v4l2_capture.c`负责有限缓冲、原始单调时间戳、内核序号、中心裁剪和所有权；不加载FPGA、不做JPEG转换、不生成ORB。每次返回独立拥有的960×720 YUYV彩色图与同帧GRAY8；原图左右各裁160像素，不缩放。工作内参为fx=757.1979、fy=757.9716、cx=499.6236、cy=352.7898，五个畸变参数保持用户标定值。原始Y分量送7015的真实PL，彩色图保留在KV260供后续DPU和赋色。

后台处理跟不上时，入口选择已排队的最新帧；传感器序号跳跃和跳过总数均保留。采样序号与传感器序号分开记录，避免无限排队。颜色按设备报告的BT.601 limited-range转换，格式、色彩参数、尺寸或时间戳不符合约定则明确失败。

实际180帧组件结果：

| 路径 | 墙钟处理速度 | 说明 |
|---|---:|---|
| 相机采集、裁剪、逐帧颜色转换、校验 | 40.62 FPS | 4.431秒；保存3张样例，跳过16个传感器帧 |
| 上述路径加7015真实PL ORB与两板网络往返 | 20.22 FPS | 8.902秒；跳过231个传感器帧；特征669–702个/帧 |

PL网络往返中位数27.182 ms，P95为30.151 ms；收到的180个完整PL结果均通过原有ABI和统计检查。颜色与灰度配对校验无差异，没有CPU ORB。两板目前通过路由器连接；尚未验证物理单网线直连。此项是输入和前端组件验收，不包含完整PS建图、DPU深度、稠密融合、GPU显示或相机运动定位验收。静止画面不能证明单目建图完成。

在KV260项目的`sources`目录构建和运行（参数路径均由当前项目提供）：

```sh
bash orb60/kv260/camera/build.sh ../camera_build_NEW
bash orb60/kv260/depth/runtime_exec.sh .. python -m orb60.kv260.check_camera_ingest \
  --library ../camera_build_NEW/liborb60_v4l2.so \
  --source-camera orb60/kv260/config/camera_usb_20261103/camera_source.csv \
  --camera orb60/kv260/config/camera_usb_20261103/camera_orb.csv \
  --output ../camera_run_NEW --frames 180 --fps 60 \
  --root "$(realpath ..)" \
  --connection orb60/kv260/config/two_board_connection.example.json \
  --endpoint '[fe80::20a:35ff:fe00:122%eth0]:5600'
```

省略`--root`、`--connection`和`--endpoint`可单独检查采集；该模式不会宣称物理ORB通过。输出包括逐帧CSV、实际协商参数、库和源码SHA256、三组彩色/灰度/原始PL样例及明确状态JSON。前端由本次SSH进程持有，结束后受控停止并释放7015所有权，不改原生产启动项。

首次开发中的失败保留在`capture_only_a/RESULT.json`：V4L2的QBUF会重写输入输出结构中的序号，旧代码在QBUF后取序号，被独立单调检查拒绝。修复为QBUF前保存DQBUF身份，并增加模拟QBUF重写字段的C单元测试；实际通过记录为`capture_only_b`和`camera_physical_orb_a`，不会将旧失败改为成功。

## 原生PS接入与DPU组件

`ps/KvCameraPipeline.h`和`ps/build_camera_entry.py`将相机接入原生PS程序。相机驱动增加类型明确的C接口，整数纳秒时间戳不经过浮点JSON解析；灰度仍是原始Y分量，RGB是同帧转换。有界队列最多保留1个待处理相机帧，传感器跳帧写入`camera_frames.csv`。旧录像入口及建图库不改写。构建新入口时逐项核对保留库和源码哈希，单独编译相机入口和驱动，再链接原建图库。

实际`network_camera_native_20261103_a` / `runs/camera_native_300_20261103_a`已完成300帧：全部调用7015物理PL、无CPU ORB，原生`TrackMonocular`处理段13.051秒、约22.99 FPS；传感器跳过303帧，已记录。当前静止画面未初始化出地图，0有效位姿、0选中关键帧，因此这是输入/初始化组件通过，不能称为有效建图22.99 FPS。`camera_mapping_status.json`明确为`INPUT_DRAINED_NO_MAP_INITIALIZED`，不会创建`NATIVE_COMPLETE`或伪造地图导出。

独立入口`run_camera_mapping.py`执行上述有限帧组件测试。构建命令：

```sh
python3 -m orb60.kv260.ps.build_camera_entry --root .. \
  --base ../network_bounded_published_mapper_20261103_b --output ../network_camera_NEW
```

本次启动`3b6ef6dc-0cda-4891-8016-93ca15487d06`已重新显式加载匹配的DPU＋点核平台，使用`deployment_tagged_20261103_f`和`checks_tagged_20261103_f`；配置标识核对、4组实际点核向量和DPU目标profile均通过。随后`check_camera_depth.py`对保存的USB相机第90帧进行了真正DPU推理，7次DPU子图中断，输出256×256相对逆深度。worker记录单帧推理约96.20 ms；含进程/模型启动的调用约1.735秒，不作为整机FPS。worker保持`DPU_RUN_REQUIRES_NUMERICAL_GATE`，没有把无真值的新相机场景称为深度精度验收。

相机尚无地图时，不生成世界坐标点云。`dense_service.py`新增显式相机模式：首次真正选中关键帧后才启动DPU worker；若原生证据确认0有效位姿、0关键帧、0点块，则只允许`COMPLETED_NO_MAP_INITIALIZED`状态。旧录像生产入口默认不启用此分支，原有空输入/点云验收门槛保留。

## 相机统一入口

KV260桌面已有 **摄像头建图与彩色点云**，执行`run_camera_session.sh --desktop`，默认最多处理600帧。出现“等待初始化，请缓慢平移相机”时，需要实际平移摄像头以产生视差；不要只在原地转动。该入口与旧的保存视频入口分别保留。命令行可运行：

```sh
# 在KV260桌面终端、项目sources目录执行，300为本轮最大处理帧数
bash orb60/kv260/run_camera_session.sh 300
```

统一编排源码为`run_camera_system.py`，配置为`config/camera_system.example.json`。它只读核验本次启动的DPU＋点核证明，核对实际链接的建图库和相机内参，然后依次运行7015 PL服务器、原生相机/PS程序、稠密服务与Mali独立地图窗口。RGB、灰度、位姿和关键帧按原始整数时间戳关联；选中关键帧的输入时间间隔为1秒。完整定位仍要求同一相机内参和对应地图。

实际`runs/camera_system_300_20261103_a`已完成300帧启动、接入与退出检查：CPU ORB为0；两个地图窗口均为ARM Mali-400 MP硬件GLES2，收到末帧299，动态源帧表读满300行。原生输入/初始化处理段12.205秒、约24.58 FPS；窗口收到新快照约5.87次/秒。由于没有位姿/场景变化，GPU仅绘制初始化网格几次，不能据此评价真实点云的绘制帧率。结果明确为`ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED`，稠密服务为`COMPLETED_NO_MAP_INITIALIZED`：0关键帧、0次DPU推理、0彩色地图。前述单帧DPU样例属于独立组件证据，未冒充本次相机整链DPU执行。

单独运行 `run_camera_system.py` 时，组件结果保存在对应的`RUN_control/RESULT.json`。桌面入口现已接入下述完整流程，新的结果位置为`camera_sessions/session-*/run/session.json`，其中建图组件记录在`run/mapping_control/RESULT.json`。每次分配新目录，终端以中文说明是否真正完成地图。重启后旧的DPU预检会被拒绝，不自动加载硬件。本次已用旧boot预检做拒绝测试，启动前退出并保存`FAILED_STARTUP`记录。运动初始化、相机彩色世界地图、同相机7015定位及物理单网线直连仍待验证。

## KV260 发图、7015 原生定位

`run_7015_network_localization.py`提供独立有限帧入口，对应7015的 `network_camera.cpp` 和端口5605。真实相机采集仍在KV260，但固定地图定位在7015的PS执行，ORB仍在7015的PL执行。摄像头图像、整数时间戳、原始序号和工作内参哈希绑定，接收确认仅确认图像收到，最终检查原生PL/位姿/HDMI报告。

新路径已完成实际120帧相机探针，全部帧配对无差异，CPU ORB为0、HDMI无错误。原生入口起止范围4.85秒，约24.74 FPS；这只是没有地图时的输入/PL/HDMI速度，不能称为定位或建图速度。实际跳过66个传感器帧，未隐藏丢帧。当前没有安装对应新相机的地图，0有效位姿；显式无地图探针不会借用旧录像的910像素焦距地图。

另用原录像和原地图对新接收路径跑满2273帧，2135帧有效；全部位姿、特征、匹配、内点与原SD入口完全一致。该录像诊断与真实相机探针分别保存。串行ARM交叉编译、11组实际C++协议故障测试、7015 ARM几何自检及电脑325项检查通过；4项平台相关检查在Windows跳过。完整说明及正常定位所需地图条件在 [7015入口说明](../board_7015/README_ZH.md)。

## 摄像头建图、地图交接及定位的完整入口

桌面入口仍为 **摄像头建图与彩色点云**，脚本 `run_camera_session.sh` 现调用 `run_camera_two_board_session.py`。默认先采样600帧建图，再采样600帧定位；两阶段均使用KV260上的同一USB摄像头。建图时7015 PL提供特征，KV260 PS建图，选中关键帧间隔至少1秒，在真实DPU推理后融合RGB点云，Mali显示。成功交接后，7015 PS负责固定地图定位，HDMI使用固定彩色背景叠加实时轨迹。

新增 `handoff_camera_7015.py` 重新检查真实相机序号、丢帧、PL结果、单地图连续性、至少5 FPS的完整几何速度、DPU选中关键帧、最终点块及Mali交付；随后复用原地图封装。保存视频的旧交接门槛不改为摄像头门槛。`install_camera_map_7015.py` 校验相机哈希、稀疏/彩色地图及有界归档，并在全新的7015发布目录执行原生导入和逐字节往返校验，不覆盖原生产地图。

没有初始化地图时，完整入口以 `CAMERA_INPUT_COMPLETE_NO_MAP_NO_HANDOFF` 和退出码2结束，明确不传图、不启动定位。实际120帧新入口已验证该分支，7015 PL及Mali通过，0位姿、0 DPU任务；不会借用原录像地图继续演示。另用明确的 `--recorded-diagnostic` 模式测试新安装程序：真实7015导入270,871个RGB点的原录像地图，并对300帧原录像完成配对定位，全部位姿/匹配/内点与旧基线一致。此正向组件检查仍不算新相机建图或定位。

上述静止组件阶段的电脑检查为351项通过、4项平台相关跳过；它没有证明移动摄像头的完整链通过。后续真实移动记录如下。

## 2026-11-03 实际移动相机记录

本轮 `runs/camera_motion_1200_20261103_a` 实际采集1200帧，1123帧有位姿；第3帧初始化，初始化后有效率93.82%。只创建map0，没有重置或拼成多张地图。59个选中关键帧实际进入DPU，最终形成333,261个RGB点；反投影在KV260 PL执行、融合在PS执行、窗口由Mali渲染。原生图像处理段14.19 FPS；包含最终优化及稠密链收尾的几何吞吐为7.77 FPS，两者计时范围不同。

早期第50–111帧连续失跟62帧，另有零星失跟，因此原结果保持 `FAILED_TARGET_GATES`（未达到98%稳定性），不改成已验收。显式 `handoff_camera_7015 --diagnostic` 仅允许继续做下游联调；它重算其他硬件、单地图、速度、颜色和帧身份门槛，保留原失败记录。常规完整入口仍要求稳定性通过。

本地图已在7015发布目录 `/opt/orb-demo/kv260_network_camera_motion_20261103_a` 完成原生导入及逐字节往返校验，版本 `556ab232a814a878aa32fb23f49da2d720faee93bf18b99d25d7e0c56d355422`。新摄像头757像素焦距的标定与地图一致，未混用旧录像910像素焦距地图。7015使用新增的固定地图多视角描述子匹配；该功能只在PS执行，Hamming距离、比例和几何门槛保持原值。

接着 `runs/camera_motion_localization_20261103_a` 对1200帧真实摄像头输入运行7015 PL、PS和HDMI，帧身份全部一致、CPU ORB为0，彩色背景构建1次复用1199次，HDMI无欠载或AXI错误。但当前画面是鞋柜／口罩区域，与刚建的显示器／桌面区域不同，0帧位姿有效；结果为 `FAILED`，不能据此声称实景定位通过。用户随后离开现场，明确要求先跳过移动相机测试。现场重定位和两板物理单网线测试均为待验收。

已有地图可以直接续测，不必重新扫描。在KV260项目根目录执行：

```bash
bash sources/orb60/kv260/run_camera_localization.sh --diagnostic \
  camera_motion_native_install_20261103_a/RESULT.json 3600
```

每轮记录位于 `camera_localization_sessions/localization-*/run/RESULT.json`，所选地图的校验记录位于同轮 `SELECTION_RESULT.json`。诊断地图必须显式指定 `--diagnostic`；脚本核对安装记录、输入模式和相机哈希，不重新建图或自动加载硬件。回来后先对准原来扫描的显示器／桌面，朝向与距离尽量接近，识别后再缓慢平移。
