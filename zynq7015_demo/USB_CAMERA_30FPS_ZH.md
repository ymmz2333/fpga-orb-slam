# USB 摄像头：PS 解码、PL ORB、整机 30FPS

2026-10-24 用户将当前目标改为 USB 摄像头持续输入、PS/Linux 采集和 MJPEG 灰度解码、PL 提取 ORB，PS 建图/定位，HDMI_2 显示。历史目录名 zynq_slam_60fps 保留。原 30FPS 冻结基线、原 zynq_slam、板上 SD 选择均不改动。

## 已确认设备和当前阻点

- 用户已把摄像头接到 USB_HOST1。板端 USB 路径 1-1.1，VID:PID=1bcf:2cd1，产品名 DECXIN CAMERA，链路 480Mb/s。这是实际 USB 枚举结果，不能仅凭 VID/PID 断言感光芯片型号或实测快门性能。
- 原始 USB 描述符及解析结果：output/usb_camera_20261024_1154_descriptors.hex、output/usb_camera_20261024_1154_capabilities.json。
- 描述符明确支持 1280×720 和 1280×800 MJPEG 30FPS（还公布 10/20/60/120FPS 档）；这两种尺寸 YUY2 仅 10FPS，640×480 YUY2 支持 30FPS。当前原 ORB 输入固定 960×720，先选 1280×720 MJPEG 30FPS，水平中心裁剪 x=160，不缩放。1280×800 则 x=160、y=40；另支持设备公布的 1024×768，x=32、y=24。
- 原 Linux 4.14.0-xilinx #52 的 CONFIG_MEDIA_USB_SUPPORT 未开启，最初没有uvcvideo和视频节点。16:37已完成匹配内核的独立模块验证并临时加载，现有/dev/video0且真实采集通过；内核/SD配置保持原样，重启后仍需按校验流程重新加载临时模块。实验结束HDMI恢复原基线。
- 本机找到与既有内核来源完全相同的出厂包，SHA256=41e9c2edcf4844f625129437306dcda6f4f1abf279cb8a63d83234a3aee266b5。原 .config SHA=cc474754e590bf4665cd8a09250d68abe41197a5f2f9a7c619bffa75a173884c；Module.symvers SHA=db214db6ccdc55f73731c2c5fddb3db1410b178535cd538cc8c0d8dcb486c137。内核启用 MODVERSIONS，不能靠修改 vermagic 或强制 insmod 绕过 CRC。

## 输入代码与验证范围

- src/camera.cpp、include/zslam/camera.hpp：固定来源尺寸、显式中心裁剪，GREY/YUYV提取原始亮度字节；MJPEG使用libjpeg-turbo3.2.0直接输出GRAY8，无RGB中间帧和缩放。输入最多4MiB，来源最多1280×800，解码内部内存限制16MiB，拒绝不匹配尺寸、非8位/渐进/无损编码、CMYK、空/截断/错误帧。新增精确水平区域解码默认启用，保留全宽A/B；scratch按实际选定宽度和完整来源高度复用。
- src/ports.cpp：V4L2 单平面 MMAP，精确请求格式/尺寸/帧率，不能暗中退到低帧率 YUYV；最多8个各不超过8MiB的驱动缓冲。核对 bytesused、错误标记、单调时间戳，扩展32位序号回绕并统计缺帧；错误后归还租用缓冲并停止。非单调驱动时钟的主机取帧时间回退在 camera.json 明确统计，不能据此声称曝光到显示延迟。
- 主程序默认 target-fps=30；新增 --camera-format mjpeg|yuyv|grey、--camera-width、--camera-height。--capture-only 默认采300帧，不需要标定、不打开 UIO、不运行 SLAM，写有界采集日志、camera.json 和最后一帧 PGM；仅用于图像链路验收。
- 真正 SLAM 要求显式提供这只摄像头在协商来源尺寸下的标定 CSV，格式 width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4；裁剪仅平移 cx/cy，保存原始/ORB两份标定证据。旧录像的960×720内参不能直接套到1280×720的新相机。尚未收到新相机标定文件。
- 已测无收益的 precise 检索失效不再默认启用；默认 legacy，保留 --precise-retrieval-invalidation 实验开关及旧禁用参数。轨迹缓存仍默认关闭。旧A/B开启组已显式加开关。
- tests/fixtures/camera：4种尺寸/灰度或色度采样JPEG的独立Pillow亮度解码与裁剪参考，另有渐进/CMYK拒绝用例。两条解码路径的逐像素参考、截断/超大头/错误编码/坏帧后复用、GREY/YUYV填充步幅、裁剪标定、序号回绕/缺帧/重复、有界标定采样与原几何等整套测试均已在Native和ARM板端PASS。实际摄像头整机SLAM/位姿验证尚未进行，不能由自检代替。

## 依赖和构建

scripts/fetch_camera_dependencies.py 固定下载并核对官方发行文件 SHA：libjpeg-turbo3.2.0、CMake3.31.10、Ninja1.13.2。JPEG 上游完整原件保存在 vendor/jpeg_turbo/upstream，provenance.json 保留每文件 SHA，禁止修改。CMake/Ninja 放在 build/tools，不安装或改全局 PATH。

This software is based in part on the work of the Independent JPEG Group.

JPEG 静态依赖由 scripts/jpeg_dependency.py 独立 CMake/Ninja 构建，单进程，配置探测和每个实际编译器入口均检查1536MiB门槛；ARM要求NEON，Native标量用于功能比对。失败或资源不足保留目录。Native配置已成功、对象部分完成，详见末尾断点；ARM依赖尚未构建，不预先宣称ARM兼容和性能。

```powershell
fpga-python.cmd scripts/fetch_camera_dependencies.py
fpga-python.cmd scripts/check.py
fpga-python.cmd scripts/build_arm_2018.py
fpga-python.cmd scripts/package_experiment.py --arm build/arm_NEW --stage camera
```

上述 check/build 自动准备各自静态 JPEG 库。低于1536MiB绝不开始下一本机编译。不要 resume 已完成的 arm_20261024_101909；新源码必须新建 ARM 构建。Linux CMake 另需显式提供 ZSLAM_TURBOJPEG_INCLUDE 和 ZSLAM_TURBOJPEG_LIBRARY 指向这版头文件及静态库。

## 可逆补装 UVC 的待验流程

scripts/build_uvc_2018.py 不重编整套 Linux，也不替换 SD 内核。它使用精确出厂生成头、.config、Module.symvers、相同 SDK2018.3 GCC7.3.1，分阶段编译 videobuf2-vmalloc、uvcvideo；出厂 genksyms/modpost 交叉编译成 ARM 用户态工具，在板上运行以生成真实符号 CRC 和模块元数据，工具本身不加载驱动。

```powershell
fpga-python.cmd scripts/build_uvc_2018.py --phase objects
# 运行所产 genksyms-stage/run.sh，取回结果（仅用户态工具，不加载模块）
fpga-python.cmd scripts/build_uvc_2018.py --phase versions --build build/uvc_NEW --results GENKSYMS_RESULTS
# 运行所产 modpost-stage/run.sh，取回结果（同样不加载模块）
fpga-python.cmd scripts/build_uvc_2018.py --phase final --build build/uvc_NEW --results MODPOST_RESULTS
```

versions阶段必须先让原内核videobuf2-memops导出符号CRC与出厂Module.symvers完全一致；否则拒绝继续。modpost不忽略缺失符号，最终ELF必须有__versions、对应vermagic。Windows抽取头的8组大小写冲突属于未用网络过滤头；编译依赖触及这些头必须拒绝。本次已完成三阶段、全部导入CRC/ELF检查及临时insmod，实采通过，具体证据见16:12阶段记录。

已尝试 objects 准备，因892MiB在 compiler_version前 DEFERRED_MEMORY，无对象。其后脚本有改动，build/uvc_20261024_120853为空的旧配方断点，不能强行恢复；资源允许后重新运行 objects。无任何模块被加载，无 SD/flash/JTAG 操作。

只有全部 CRC/ELF 检查通过、live .config匹配且确认目标板状态，才在新实验目录临时 insmod 两个模块。不能强制加载、不切 SD；模块失败先恢复基线/必要时重启，不能带 PL 故障继续复用 DMA。

## 接下来验收

Native、ARM自检、临时驱动绑定、两组各600帧采集解码和完整2273帧PL黄金回归已完成。下一步在用户方便时完成真实标定，再运行摄像头完整建图/定位/HDMI。scripts/bench_usb_camera.sh支持无标定只测采集，有标定再完整回归和1800帧实摄像头；退出/HUP恢复基线，PL异常复位。已完成的对照脚本为scripts/bench_camera_region.sh。

核对真实帧序号/时间戳、实际采集及提交帧率、缺帧、队列延迟、RSS/有界日志、LOST无效、建图位姿质量和零 HDMI欠载/AXI错误。JPEG 有损，不能要求它与原未压缩录像的黄金特征相同；JPEG像素用独立参考验收，原RAW路径另做原始特征字节回归。单采集/解码30FPS、显示扫描60Hz、旧SD31.86FPS均不能冒称实摄像头整机30FPS通过。

12:08 Native入口在 JPEG configure前因663MiB延期；UVC入口在 compiler_version前因892MiB延期。12:12可用660MiB，12:19为841MiB；随后最新Native尝试仅587MiB，在配置前再次延期，无编译器启动。当前通过 Python AST、Git Bash -n 两个板测脚本语法、固定原件/测试样本 SHA 核对；C++、ARM、驱动和摄像头运行全部未验收。SSH再次确认 live.config SHA 与出厂一致，原基线PID7695仍运行，SD/boot_id未变。现有已验证二进制仍是第十阶段 arm_20261024_101909，不能与新源码打包。断点与待验源码归档保存在 output/latest_checkpoint.json。

购置建议：先使用已接好的这一只 DECXIN 摄像头，它公布的1280×720 MJPEG30FPS符合当前输入计划，无需因驱动缺失换摄像头。全局快门/手动曝光能力以实物型号和实际控制查询为准；标定和运动场景验证完成前，不承诺位姿质量。

12:38用户要求继续，Windows可用2831MiB、无其他编译/板测，开始Native检查。便携CMake35.9s配置成功，JPEG依赖build/jpeg_native_757f3a7b25972eaa前47/130项完成；第48项编译入口测到1528MiB，按75返回并由Ninja停止。12:42为1377MiB、12:43为1374MiB、12:45为1265MiB，未再启动编译。47项对象已保留，后续源码/工具链/配方未变时运行同一scripts/check.py由Ninja原目录续编，不丢弃或重新配置为另一版本。此进展仅JPEG静态依赖部分编译，本机C++自检、ARM、UVC与摄像头实际运行仍未完成。12:39SSH再次只读确认相机480Mb/s、基线PID7695、原boot_id和SD current不变，没有实验程序。

## 标定采样和PC离线工具（实机尚未验证）

在USB候选中新增 --calibration-shots（1..60）和 --calibration-every（1..300）参数，仅可用于 --capture-only。按真实帧序号和时间戳保存最多60张960×720裁剪灰度PGM及index.csv；拒绝重复帧、回退时间戳、错误尺寸和覆盖已有目录。采样写SD会干扰帧率，capture_mode.json明确记录用途，性能测试须另开不带采样参数的运行。此项C++源码与测试尚未编译，不能视为已在板上可用。

候选通过Native/ARM并补装UVC后，可在独立板端实验目录采样，例如：

```sh
bin/zynq-slam --camera /dev/video0 --capture-only --target-fps 30 \
  --calibration-shots 40 --calibration-every 30 --output calibration-capture
```

output/checkerboard_9x6_25mm.svg 是10×7方格、9×6内角点的平面标定板，黑白方格25mm，含15mm白边，文件280×205mm。按100%比例打印并用尺核对实际方格尺寸；采样时让整块棋盘保持平整，改变位置、距离和倾角，覆盖图像四周。实际标定尚未采集，无需因此阻止无标定的采集/解码测试。

将本次采样的camera.json、calibration-frames/index.csv及PGM取回PC同一目录。使用PC专用Python离线标定，不把OpenCV加入ARM运行时：

```powershell
$taskPython = 'C:/Users/dmsun/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $taskPython tools/fetch_calibration_opencv.py
& $taskPython tools/calibrate_usb_camera.py --capture LOCAL_CAPTURE --output NEW_CALIBRATION --square-mm 25
```

离线依赖固定opencv-python-headless4.13.0.92 Windows wheel，SHA256=77a82fe35ddcec0f62c15f2ba8a12ecc2ed4207c17b0902c7a3151ae29f37fb6，解压在build/calibration_python，不修改全局Python。算法采用[OpenCV标定接口](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)的五项畸变模型，与PS一致。至少15个有效不同视角、最多60张；要求足够图像覆盖与倾角、整体重投影RMS≤0.7px、单图≤1.5px、焦距相对不确定度≤10%，并拒绝图像内径向模型折返。不通过则写拒绝原因，不生成camera_source.csv。

通过时camera_source.csv描述原来源尺寸，cx/cy已加回裁剪偏移；1280×720恢复cx+160，1280×800还恢复cy+40。主程序随后按同一显式裁剪减回偏移。不能把960×720裁剪标定冒充1280×720来源标定。工具处理所给文件，不证明文件来自当前设备；标定重投影通过也不等于独立位姿真值或完整SLAM质量通过。

PC端tests/test_camera_calibration.py共6项于13:06全部PASS，日志output/calibration_pc_tests_20261024_1306.log：已知内参/畸变恢复及裁剪坐标还原、样本不足/重复视角、NaN/错误裁剪、过大重投影误差、标定板尺寸及防覆盖、空白采集拒绝且不输出CSV。它们只验证合成几何和工具拒绝路径，不替代真实相机标定。对应C++采样测试仍NOT_RUN。

13:15资源复查可用943MiB，无本机编译/SSH/板测进程，额度主窗口已用43%，未消费重置券。13:06核对JPEG配方/工具和47对象SHA全部一致；新增采样源码不改变JPEG依赖签名。当前源码已不同于12:23待验包，必须以latest_checkpoint所指的新归档为准。Native/C++、ARM、UVC、摄像头采集及整机30FPS均未验收；下次先核对47对象再原目录续编，不能套用旧ARM PASS。

## 16:12起资源恢复后的实际进展

- Windows可用内存恢复至约24GiB，先核对47个旧JPEG对象与当前源SHA再续编。Native JPEG库完成，ARM NEON JPEG库也完成；上游原件未改。首次C++测试发现拒绝非法JPEG头后，解码器内部状态未恢复，下一合法帧会报重复SOI；已在错误路径重建解码器并保留固定像素缓冲，原拒绝/复用测试随后全部通过，未放宽测试。
- 第一版USB程序build/arm_20261024_161853交叉编译/ABI检查PASS，板端全套CPU自检PASS。对应独立包slam60_camera_20261024_162604，SHA35a991aa8bd0b4c510a5b5d91c29ebba670dac24098f2bf930585e3d08a5af22；不替换SD基线。
- 本次连接时板卡已是新的boot_id=38608b1d-6bdb-4172-87d5-93e3e6c83421，内核/config/SD current未变。启动日志显示自动加载的旧map.zmap为0字节，服务已停止。已将该空文件和日志复制到独立boot_map_evidence_20261024_1618留证，然后启动未修改的原基线控制器，恢复运行。没有修改/删除旧地图或更改SD选择。实验结束仍恢复基线。
- UVC构建build/uvc_20261024_162629三阶段完成。板端ARM genksyms生成的3个已知videobuf2-memops CRC与原内核全部一致；modpost未忽略缺失符号。额外直接解析最终ELF，videobuf2-vmalloc的32项和uvcvideo的110项版本CRC（含module_layout=0x64cd2ee2）全部匹配出厂导出表/本次VMALLOC导出，所有强全局导入都有版本项，vermagic严格匹配。证据import_crc_verification.json。
- 再次核对live.config和boot_id后，从独立目录临时insmod成功，现有/dev/video0，DECXIN CAMERA。没有修改内核/BOOT.BIN/启动脚本，重启后模块不会自动保留。内核记录了debugfs目录和media entity类型提示，未阻止本次采集；不能据此宣称所有控制/媒体拓扑均已验收。
- 第一版实摄像头600个不同帧全部采集/灰度解码成功，序号0..599连续，零sequence gaps、零主机回退时间戳，协商1280×720 MJPEG 1/30，实测时间戳平均29.78776096FPS，解码线程CPU22.1060583ms/帧。驱动MMAP3缓冲共5529600B，解码scratch921600B。原始时间戳间隔最大234.003ms，需进一步看启动阶段与稳态，不把均值当每帧实时性通过。证据output/usb600-evidence_20261024_162604.tar.gz SHA6147909a95f76ac6e2ad2e8c28de139db617cdfc9c775e92a7fdfb29cf1cb3b2。此项只有采集/解码，没有运行摄像头SLAM/PL/HDMI。当前抓拍细节较模糊，需在用户方便时检查实际对焦/运动条件。
- 第一版原RAW2273帧全部黄金字节一致，HDMI零欠载/AXI错误。首轮交互终端的后续输入触发控制键，位姿结果无效并保留为raw-stdin-contaminated。隔离stdin后的完整回归2064有效，31MiB以下RSS，但使用默认12000点/64关键帧，整体23.7585FPS；这不是3000点/16关键帧基线的公平性能对比。当前bench_usb_camera.sh补齐相同3000/16边界并关闭应用stdin，后续新候选按该工作量验收。不能丢弃失败证据或将12k帧率混入基线比较。
- 用户明确要求稍后再标定，先做其他工作。真实标定/摄像头建图仍待用户方便时进行；目前不使用旧内参代替，不把采集29.79FPS称为摄像头整机30FPS。

精确水平区域解码已验收组件收益：默认--jpeg-region-decode，仅对960像素宽保留区域执行像素重建，所有来源行仍解码到帧尾，继续使用原精确IDCT/错误检查，再按原y偏移取720行。--full-jpeg-decode恢复全宽路径用于A/B；camera.json记录模式与实际scratch。四种原样本在两条路径均与独立Pillow灰度参考逐像素相同，坏帧后恢复及所有原测试在Native与ARM均PASS。没有RTL改动。

## 17:07区域解码验收结果与当前断点

当前已验证软件build/arm_20261024_165028；实测独立包slam60_camera_20261024_165445，SHA85325cddea64a357a25bbd1d87d65870395d2a4545752d566bdee7cd3caaa330。Native/ARM构建及板端全套CPU自检PASS。源码与该ARM清单一致，禁止与旧二进制混装；之后仅文档/断点更新不代表重新运行了板测。

| 600帧真实USB采集，仅解码 | 全宽 | 水平区域 |
|---|---:|---:|
| 平均解码线程CPU | 22.2180ms | 19.8694ms |
| 包含启动的时间戳FPS | 29.9576 | 29.9666 |
| 跳过前30帧的稳态FPS | 30.09134 | 30.09134 |
| 首个帧间隔 | 120.006ms | 114.019ms |
| 序号缺口/主机时戳回退 | 0/0 | 0/0 |
| 解码scratch | 921600B | 691200B |
| time -v测得峰值RSS | 37.515625MiB | 37.515625MiB |

本次场景解码CPU减少10.5709%，scratch节省230400B（225KiB）。两组都是独立的真实传感器序列，不能宣称两次现场画面逐帧相同；精确像素依据是Native/ARM的独立参考样本测试。本次画面细节较模糊、压缩数据约52KB/帧，不能把这里的耗时承诺为所有清晰场景的上限。设备帧间隔约30ms/36ms交替，帧率均值不是每帧33.3ms期限通过。

相同3000点/16关键帧的原RAW2273帧：平均30.31203386FPS，2045有效位姿，2273帧黄金字节全部一致、2273次HDMI新内容提交、零丢帧/欠载/AXI错误，RSS17.8125MiB。10秒滚动窗口最低29.46494FPS，故持续窗口≥30仍未达到。原录像参考覆盖2042/2081=98.1259%，位置P95=0.00607784相对地图单位、旋转P95=0.553859度；只是同录像原SLAM参考，非独立真值或米制，不能用来声称真实相机定位精度。

完整证据output/usb-region-evidence_20261024_165445.tar.gz，SHA e0070aa4f9960c77aac7f3a104cc47906e6add7456973f96b384d17a71736a93；已取回核对并安全解包，含UVC阶段、CRC元数据/模块、启动空地图留证、两组采集、ARM自检、RAW黄金/时序/位姿/HDMI日志。解包目录下usb_region_summary.json和raw-regression/analysis.json保存全部统计。首轮stdin干扰和12k地图实验另保留证据，均不混入上述性能验收。

基线已恢复PID2060，SD current和内核/config未改。冻结基线与原zynq_slam的85项源和110项归档哈希全部复核PASS。用户要求标定稍后进行；当前留在可继续标定的状态，实摄像头三维建图/定位/HDMI整机30FPS仍未验收。

## 17:38起：Q12-25-1.5实机标定与调焦准备

用户恢复标定并通过文字和完整规格表确认第一款Q12-25-1.5：板外形25×25mm、有效图案18×13.5mm，12×9个方格，单格1.5mm，因此OpenCV采用11×8个内角点。不能沿用旧9×6内角点/25mm设置。PC工具已增加--columns/--rows，保留旧默认兼容；8项测试PASS，包括该88点小尺寸模型的已知内参恢复、错格点拒绝和所有原门槛。命令为：

```powershell
& $taskPython tools/calibrate_usb_camera.py --capture LOCAL_CAPTURE --output NEW_CALIBRATION --columns 11 --rows 8 --square-mm 1.5
```

17:42取一帧检查，11×8棋盘未检出，图像明显模糊，中心外整帧Laplacian方差约5.52。此短抓拍与旧基线同时运行，仅作画面检查，30帧存在14个序号缺口，不能用于性能验收。PGM SHA4e1184e88e1c71bf75375f84c65f7b05da64281ca9df4d4e2292f36a6ff62b82，保存于output/focus_q12_20261024_1742。用户答复需要先调整对焦。

只读V4L2控制枚举返回EIO，未写任何控制。独立核对原始USB描述符，Camera Terminal bmaControls=0x0a0a，未声明FOCUS_ABSOLUTE/FOCUS_AUTO；不假设存在软件/电动调焦。应配合实际镜头调焦机构或改变拍摄距离，以方格边缘清晰且完整入镜为准。小板能否覆盖足够视场需看实际对焦和距离，不降低标定覆盖/重投影/姿态门槛。

新增--camera-preview --camera /dev/video0 --hdmi-uio /dev/uio0，专用于未标定调焦：两线程、有界灰度池/队列，实时原灰度画面与中心320×240的Laplacian方差引导数值；UI明确CAMERA ONLY/NO POSE/SLAM DISABLED，不提取ORB、不运行SLAM、不创建虚构内参。清晰度分值受图案、光照和噪声影响，只作调焦反馈。可选--calibration-shots/--calibration-every保存有界原帧PGM及真实索引，与PC工具兼容。暂测脚本bench_focus_preview.sh默认3600帧约2分钟，退出恢复基线；应用stdin关闭，受控终止先回收自身子进程，再恢复服务，PL失败按既有规则复位。

新的Native整套自检已PASS，新增测试覆盖模糊/清晰顺序、像素只读、无效尺寸、预览禁止有效位姿、预览图像全部像素保持及回到原UI逐像素一致；PC标定8项PASS。此时新ARM/HDMI预览仍待接下来的实际验证，不能套用旧ROI版本的板测PASS。当前C++与旧arm_20261024_165028不同，暂不可部署为基线；当前源码/阶段状态见latest_checkpoint。RTL未变。

## 18:10起：实际HDMI调焦与Q12采样

当前焦点预览版本build/arm_20261024_180124已完成Native整套、ARM交叉/ABI及板端整套CPU自检。当前输入SHA与该构建相符。独立包slam60_camera_20261024_180726，SHA539458d82fbd9aa52ae615698cc3cdbf15bf6b34dcb90af82f98355e4306a8a8；未替换SD基线。600真实帧预览全部提交，摄像头序号0..599连续，零主机时间戳回退、HDMI欠载和AXI错误，峰值RSS17.55078125MiB。预览wall均值29.52887779FPS、来源时间戳均值29.95759125FPS；两者均不代表完整摄像头SLAM吞吐。所有371712个显示相机像素与保存PGM的原采样/RGB565转换独立逐像素一致，最后清晰度数值与PC同一中心区域方差重算一致。界面已视觉核对，明确未标定、无地图/位姿。

证据output/focus-acceptance-evidence_20261024_180726.tar.gz，SHA11da47f829c277ea56b175ba4232594f1fcca349ea05c896ef9b4bb81f7d8f75，已取回校验；解包下verification.json保存检查结果，dashboard.png为真实板端UI快照。该版本的改动用于未标定预览，未重新宣称旧ROI版本的RAW2273板测为当前版本的回归。真正SLAM前仍需匹配该版本的RAW黄金回归。

用户先要求重拍，又要求先调焦；只对核实cmdline的当前实验子进程发送TERM并等待队列清空/原基线恢复，然后按新目录切回预览。calibration-q12-01保存40张原PGM，证据SHAe77aa0ff5b79d5bcefa2cdc038951c4a804dee2f21892072212b6d6fb8568cef；calibration-q12-02是用户要求调焦时结束的组，均保留，不冒称已通过标定。用户再次明确“已清楚，开始采样”后，calibration-q12-03已采集1800帧并保存40张，每45帧保存一次，约60秒；1800次HDMI提交、零欠载/AXI，峰值RSS17.5078125MiB。采样有SD写入，不作为吞吐验收。第三组实际角点/覆盖/倾角/重投影拟合将在PC检查后单独记录，此时还没有验收相机内参，也没有运行实摄像头SLAM。

## 第三组实际标定：35张通过，保持当前对焦位置

第三组及中断第二组/调焦预览已取回，output/calibration-q12-03-evidence_20261024_180726.tar.gz，SHAc37e24613676a7652980554fc82357b429b95379c65a2311987ab73823ba1531。第二组在用户要求先调焦时已运行1557帧、保存35张，第一组40张、第三组40张均保留。每组真实序号无缺口、无伪造帧身份，第三组1800次HDMI提交、零欠载/AXI；只运行预览/采样，无ORB提取或SLAM。

整幅图的SB检测起初未识别小板，保留初次拒绝报告。定位为桌面/显示器背景干扰后，PC工具增加确定性的重叠原像素窗口和完整网格classic后备检测，不缩放、插值、变换图像，也不补造缺失角点。局部坐标只加回ROI偏移，并统一在完整原图做亚像素细化；邻近角点间距35%以上的细化跳变拒绝。第一版实拍一致性测试发现局部SB估计随窗口上下文偏移2.62px，测试未放宽；统一原图细化后两种ROI结果最大差约0.0032px，原0.3px断言通过。两张实际PGM已作为固定SHA回归样本保存在tests/fixtures/calibration/，provenance记录原帧序号/时戳及证据SHA。新PC工具12项测试PASS，日志output/calibration_q12_detector_tests_20261024_1838.log，包括已知像素位置、实拍SB/classic坐标、原内参恢复和全部旧拒绝门槛；这些PC改动不改变当前ARM输入SHA，不需要重复编译固件。

第三组40张中36张识别出完整88个内角点；第一轮整体RMS0.63119px，但frame1305单图RMS1.75192px超过原1.5px门槛，故保留整体拒绝报告。增加明确且有界的单次图像质量筛选：只排除初次拟合RMS>1.5px的图，最多3张且不超过输入10%，保留至少15张，之后只重算一次；全部覆盖、倾角、整体0.7px、单图1.5px、焦距不确定度10%及模型不折返门槛保持不变。不得反复删图凑通过。超筛选上限、全噪声、低视角数和原坏重投影测试仍拒绝。

最后35张拟合通过：RMS0.5673895px，最大单图1.2768808px，法向最大分离42.9677度，焦距相对标准差约2.78%。原40张全部保留，frame1305的排除原因/初次误差和初次整体拟合均写入quality_filter审计字段。结果在output/calibration_q12_03_checked_20261024_1840/，camera_source.csv恢复1280×720来源主点cx+160，应用再按相同裁剪减回。不使用旧录像内参或地图替代。

此结果是当前镜头对焦位置下、这批实拍棋盘的重投影拟合通过，尚不等于留出集/独立真值/真实运动SLAM精度验收。后续保持镜头对焦位置；改变对焦需重标。实摄像头整机30FPS与实时建图仍待相应板测；采样吞吐及HDMI60Hz均不冒称该目标已完成。18:38附近再次复核原/冻结85项源码和110项归档SHA全部PASS，vendor原件与JPEG样本SHA一致。

## 18:53后的实摄像头测试及S1持续运行模式

用户确认配合实时测试后，当前180124程序完成600真实摄像头采集、2273原RAW黄金回归和1800真实相机SLAM/HDMI。RAW2273特征字节全部一致，2061有效，平均31.4135828FPS、10秒窗口最低29.13598FPS，零缺帧/HDMI欠载/AXI；同录像参考覆盖2058/2081，位置P95=0.0058390相对单位、旋转P95=0.54332度，不是独立真值或米制。真实相机1800帧则只有740有效（41.11%），平均24.1217336FPS，传感器序号0..2236有437缺口，时间戳帧率24.1877FPS、传感器序号节律约30.0632FPS，零主机时戳回退/HDMI欠载/AXI。RSS22.964844MiB，MPEG解码CPU24.55806ms，核心CPU15.22789ms。最近本轮统计TRACKING712、RELOCALIZED28、LOST1041、INITIALIZING19。失效位姿16个字段均为空，不输出假位姿。来源内参SHA和crop cx-160均核对正确。证据output/usb-live-evidence_20261024_180726.tar.gz，SHA cb82886814ad39f43c2369ad42f331f1f9eb90e884da555e4acf937112a3e254，分析为其解包下live/usb_live_summary.json及raw-regression/analysis.json。整机30FPS及实拍鲁棒性没有验收通过。

负载分项发现原CPU0采集+SLAM+场景复制合计40.7417ms/帧，CPU1的ORB+绘制+提交约15.1545ms。先做不改主程序的运行时调度实验，只把采集线程mask从CPU0改为CPU0,1；其余线程绑定不动，记录真实掩码，原run.json中的capture_cpu_requested=0仍是程序最初请求，不能拿它冒称实际外部设置。首脚本因板上缺taskset，在停基线/运行PL前退出；保留空拒绝日志。另编译严格限定当前实验PID/线程及命令路径的用户态辅助工具后再试。RAW2273再次全黄金一致，32.42528FPS/2040有效；另一组1800真实相机29.88165FPS/9序号缺口，但只有1个有效位姿、57地图点/2关键帧。两组现场图像、地图和有效帧工作负载不同，不能将24.12到29.88称为保持质量的因果提速或整机30FPS通过。该实验结束时恢复旧基线的行为已被用户后续“只用摄像头，不播放测试画面”指令覆盖。

最新用户要求板载S1重置、持续真实摄像头、停止测试录像。手册确认S1=PS_MIO47；实际DT keys/key0的gpios=47、linux,code=103（KEY_UP），key1为PL按键/KEY_ENTER28，不能混用。通过独立SDK2018.3构建tools/s1_reset_bridge.c与tools/capture_affinity.c，build/s1_controls_20261024_192801编译/ARM EABI硬浮点检查PASS；板上--selftest通过短按/长按/重复/错误按键/抖动/初始已按下与FIFO传送。bridge独占grab输入设备keys的event0，只有新S1按下边沿向独立0600 FIFO写r，复用现有Slam::reset，不改ORB/相机/建图算法。SYN_DROPPED会读当前按键状态重新同步，不补造按下。状态JSON原子覆盖，按键不产生无界日志。

19:15至19:20之间板子发生新的外部重启，boot_id变为d2c5a01f-3203-43e0-9f56-6f9c068a03a8；当时摄像头模式启动命令尚未执行。已停止开机自启的录像服务，核对原4.14#52、live.config SHA及SD current一致后，SHA确认并重新临时加载同一UVC模块，恢复/dev/video0，没有修改内核/BOOT.BIN/SD选择/启动脚本。源helper及部署包output/s1_controls_20261024_192801.tar.gz SHA d08de2314128ad0b1a0d37cbd17cfa40152f174b74f746e84e5b6d69446821f5。

scripts/run_camera_s1.sh现已在原独立实验目录下运行camera-s1：controller1298、真实相机主程序1311、S1桥1329。--frames0持续采集，3000点/16关键帧边界、CSV3600行×3段，stdout关闭，保存地图/快照在正常退出时执行。采集线程使用CPU0,1外部绑定，独立JSON记录该事实，不能据此宣称已经验证30FPS。用户已确认短按S1后地图/轨迹重置且画面继续刷新；随后状态计数观察到5次请求，无输入溢出重同步。主程序/PL没有改，仍是已验180124二进制；新增控制工具单独留存构建/自检证据。

这是一项持续运行服务，不是到时退出的基准测试。用户最新指令要求旧录像服务保持停止，退出不自动恢复录像，未来原RAW回归只能离屏验证；不要把当前运行锁视为旧锁清理或随意结束相机服务。原SD启动配置仍保留不变，因此重启不会自动安装临时UVC或启动本模式。PL/CPU错误停止后要检查，存在PL故障时先复位，禁止静默重试DMA。

当前频繁LOST尚未解决。实时抽样已有1573个在线地图点/16关键帧，但最近300帧均LOST，每帧约290.77特征而无通过验证的位姿内点。Slam无地图时进入INITIALIZING，LOST说明已有地图但当前跟踪/重定位失败；日志的0内点表示验证失败后清空，不证明候选匹配恰好为零。现实现丢失后尝试旧图重定位，不自动建立新子图。当前地图来自本次相机在线生成，启动没有--load/--import-map，S1会清空它并重新初始化。它是稀疏地图，不是稠密重建，也不能称为完整原RK3588 ORB-SLAM3实现。录像测试加载配套旧图且不需要MJPEG解码，验证了特征字节和旧图回归；它不能替代任意实拍从零建图/恢复验收，下一步应针对匹配/初始化/重定位和成像证据诊断，不降低质量门槛。
