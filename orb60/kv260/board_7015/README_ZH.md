# 7015 彩色地图定位入口

2026-11-03最新状态：移动USB摄像头已生成对应757像素焦距标定的地图和333,261个RGB点，并在 `/opt/orb-demo/kv260_network_camera_motion_20261103_a` 完成原生导入／往返校验。原建图稳定性为93.82%，仍保留未通过记录；摄像头随后对准未扫描区域，真实1200帧定位未取得有效位姿。用户离场后要求暂缓现场移动测试。回来后使用KV260桌面 **已有地图摄像头定位（联调）**，先对准原扫描的显示器／桌面即可续测，无需重新扫描。操作与真实结果见 [相机记录](../camera/README_ZH.md#2026-11-03-实际移动相机记录)。

当前相机配置选择 `/opt/orb-demo/kv260_network_camera_multiview_20261103_a` 的PS程序：固定地图匹配可使用同一地标已保存的多视角描述子。运行参数为 `--fixed-map-multiview`，默认关闭，由明确的连接配置启用；PL、描述子格式与原匹配／几何阈值不变。相同旧录像地图上的配对实测为2273帧、2163帧有效，初始化后全部有效，28.30 FPS。这是保存视频的配对定位验证，不是实景摄像头定位验收。

该PS程序随后已接回从头到尾的完整视频流程：新建的一张272,779点彩色地图自动交接至 `/opt/orb-demo/kv260_complete_multiview_session-complete-multiview-20261103-a`，原生导入／往返后2273帧定位全部处理，2163帧有效、初始化后全部有效，27.80 FPS，HDMI无错误。KV260桌面视频入口为 **两板建图与彩色定位（视频）**。这轮没有复用之前的建图结果，也不代替实景摄像头／物理直连验收。

本目录的启动脚本用于已安装的独立 SD 发布目录。它不加载 FPGA，不修改内核或启动文件，也不停止其他占用 UIO 的程序。

发布目录包含固定校验的 `bin/zynq-demo`、地图输入 `map/`、7015 原生地图存储 `maps/` 和 `SHA256SUMS`。`map/dense_environment.bin` 保存 KV260 实际 DPU 重建、最终位姿修正后的 RGB 点，绑定同一稀疏地图与相机参数。它用于 HDMI 展示，不参与定位匹配。

2026-11-03 固定视角版本把彩色点云预先投影为 RGB565 背景；逐帧复制背景，再叠加轨迹和当前位置。定位中的观测次数变化不会重建彩色背景，更换地图或颜色会使缓存失效。历史轨迹的投影也使用有界缓存。`render.part*.csv` 记录绘图、显示提交和背景重建次数，建图或定位帧率与 HDMI 的60Hz扫描刷新率分别统计。

已验证的新入口为 `/opt/orb-demo/kv260_migration_20261103_static_background/run_recording_localization.sh`。同一270,871点地图与2273帧SD视频输入完整运行69.780秒（32.57 FPS），2135帧有效；背景构建1次、复用2272次。旧入口保留，原生产自启动未切换。

在7015终端运行：

```sh
./run_recording_localization.sh
```

默认回放板上原始2273帧 SD 视频输入：对应原录像第24至2296帧。ORB由7015的PL实际提取，固定地图定位由7015的PS完成；HDMI显示相机特征、彩色环境点云与定位轨迹。KV260无需参与本次定位计算。它不是实时摄像头测试。

日志保存在该发布目录的 `runs/` 下，每次分配新的目录，不覆盖前次结果。已有摄像头服务或ORB服务器占用UIO时，应先明确停止对应程序；脚本不会自动杀进程、清空地图或重载硬件。

当前已验证输入的SHA256为 `4bc70b950796a237c57059ae709f2c0d1aca20a01223ee6eee8bcdd113bdc8fc`；时间索引SHA256为 `602825454b8cd0fcabc3ca9184a78811a7907c1eae2f8ee09f77cec649cf2f6a`。原始文件不重复打进发布包。新摄像头必须使用对应标定和明确输入格式，不能把录像借用内参当作新摄像头标定。

## 摄像头接在 KV260 时

新增 `run_7015_network_localization.py` 和 `run_network_camera_localization.sh`：KV260只采集、裁剪并发送GRAY8，7015继续用自身PL提取ORB、PS做固定地图定位、HDMI显示。控制端不代替7015计算位姿。两种输入分别显式选择 `live_camera` 和 `recorded_diagnostic`，不自动相互替代。

7015新接收源在 `zynq7015_demo/src/network_camera.cpp`。固定960×720图像、整数纳秒时间戳、传感器序号、输入模式和相机标定哈希共同绑定；图像及头部校验错误、帧重复/乱序、提前断开均报错并锁定故障。接收确认仅代表图像已收齐，不代表ORB或位姿完成。帧处理与HDMI完成需检查最终原生报告。入口共用UIO独占锁，不加载PL、不改原SD启动项。

新程序单独安装在 `/opt/orb-demo/kv260_network_camera_20261103_a`。`build_network_camera.py` 串行交叉编译，`check_network_camera.py` 的11组真实C++接口测试通过，7015 ARM几何自检通过。原来的SD发布目录和二进制保留。

实际完整2273帧诊断输入从KV260发送到7015，2135帧位姿有效；逐帧时间戳、有效性、特征数、匹配数、内点数及位姿矩阵与同输入的原SD基线完全一致。彩色背景构建1次、复用2272次，HDMI无欠载或AXI错误。该运行使用原录像的910像素焦距标定及其地图，不能用于新的757像素焦距摄像头。

此前KV260 USB3摄像头另完成120帧真实输入探针，全部帧身份校验一致、CPU ORB为0、实际PL与HDMI通过。该早期探针使用新的757像素焦距标定及空的 `maps_live`，0有效位姿；它没有安装旧录像地图，也没有宣称新摄像头定位完成。`--allow-unmapped-input-probe` 只允许显式无地图的真实相机探针；正常定位要求已安装对应相机地图。

下面保留早期接收路径的命令形式；其中旧发布目录没有新摄像头地图。当前已安装地图请使用上面的桌面入口或 [相机说明](../camera/README_ZH.md) 中的 `run_camera_localization.sh`：

```sh
bash orb60/kv260/depth/runtime_exec.sh .. python -m orb60.kv260.run_7015_network_localization \
  --root .. --connection orb60/kv260/config/two_board_connection.example.json \
  --release /opt/orb-demo/kv260_network_camera_20261103_a \
  --endpoint '[fe80::20a:35ff:fe00:122%eth0]:5605' --mode live_camera --frames 600 \
  --camera orb60/kv260/config/camera_usb_20261103/camera_orb.csv \
  --source-camera orb60/kv260/config/camera_usb_20261103/camera_source.csv \
  --library ../camera_ingest_20261103_a/kv_native_b/liborb60_v4l2.so \
  --output ../runs/NEW_CAMERA_LOCALIZATION
```

以上早期发布目录没有新摄像头地图，因此该命令仍会拒绝正常定位；当时的输入探针另加了明确的 `--allow-unmapped-input-probe`。新摄像头地图现在已在独立目录导入，实景重定位及两板物理直连仍待现场验收。
