# 板端运行与接手边界

当前网络入口为 root@192.168.1.233:22，用户授权沿用手册默认账户及已经验证的主机密钥。**交接包不保存密码或私钥**。旧 Dropbear 需要 SSH `-o HostKeyAlgorithms=+ssh-rsa`，仍必须核对主机密钥，不能关闭验证。

整理前的连接调查：电脑物理网卡为 192.168.1.100；aTrustVNIC 的 192.168.1.128/25 路由比物理 /24 更具体，普通 SSH 被导入 VPN。使用单连接 IP_UNICAST_IF 绑定曾收到该板 Dropbear banner；没有修改全局路由。22:25 物理网口已断开，后续 SSH 未能登录。因此 **不能确认板上当前进程、UVC 或相机状态**。用户最后看到录像/启动画面，这不是相机测试通过。请先恢复正确物理网络并只读确认，不盲用旧 PID。

## 先只读检查

```sh
cat /proc/sys/kernel/random/boot_id
uname -a
readlink -f /opt/zynq-slam/current
ip addr show eth0
ps -w
ls -l /dev/video0 /dev/uio0 /dev/input/event0
cat /sys/class/uio/uio0/version
cat /run/zslam-usb-camera-bench.lock/child.pid
cat /run/zslam-usb-camera-bench.lock/bridge.pid
```

期望内核 4.14.0-xilinx #52、ARMv7、原 SD release sd_ssh_20261024_001751，UIO provider wc1。SD current 仍指向原录像发布版本；没有安装摄像头自启动，所以重启可回到原服务。19:58 最后确认的摄像头 session 是 controller1298 / app1311 / bridge1329、boot_id d2c5a01f-3203-43e0-9f56-6f9c068a03a8；这些数字**只作历史证据**。

摄像头 DECXIN CAMERA 1bcf:2cd1，USB_HOST1，480Mb/s。真实支持 1280×720 MJPEG30；同尺寸 YUY2 只有10FPS，商品标称更高 MJPEG 帧率不能替代设备实际协商值。

## 已通过的固定产物

artifacts/camera_runtime/ 整合原 camera 包、S1 控制器及真实标定，部署位置仍应为：

`/opt/zynq-slam/experiments/slam60_camera_20261024_180726`

保持原 `SHA256SUMS` 和 `s1-controls/SHA256SUMS`；新增 `HANDOFF_SHA256SUMS` 核对整合后的全部内容。拷贝不代表允许覆盖正在运行的目录；先核对已有文件，单独留证。

主程序和 capture-affinity 工具均已验证，后者**硬编码**上述 candidate/camera-s1/ 输出路径作为进程保护，不能仅改 shell 路径后期待仍工作。换实验位置需在工作副本同步修改 helper 并重新构建/验证。run_camera_s1.sh 拒绝已存在 camera-s1；仅在确认本轮无进程、锁和 DMA 持有者后，才可将旧运行目录移到带时间戳的保存目录，不能删除证据或抢锁。

原内核没有自动 UVC 驱动。模块仅在验证相同内核/live.config/CRC 后临时加载：

```sh
insmod /PATH/TO/videobuf2-vmalloc.ko
insmod /PATH/TO/uvcvideo.ko
```

这里的 PATH 是经过 SHA 核对的独立模块目录。不要强制加载，不替换 SD kernel/BOOT.BIN；重启后需重新核对再加载。live.config SHA 为 cc474754e590bf4665cd8a09250d68abe41197a5f2f9a7c619bffa75a173884c，module_layout CRC 64cd2ee2。证据在 artifacts/uvc/。

UIO/PL 已由原 SD 发布配置提供时，不再并行运行 load_hdmi_board.sh。该脚本会卸载相关消费者并更换 PL，只适用于原首次 bring-up 前提，不能对现运行设备盲目执行。

条件都满足且无其他摄像头/ORB 进程后，原部署目录内通过 `sh run_camera_s1.sh` 运行。控制器会停原录像服务，持续 frames=0，独占 KEY_UP103，S1 新按下沿写 r 清图。长按/重复/抖动不反复 reset；FIFO 专用于控制，勿把 SSH 命令或口令输入应用 stdin。

正常退出不恢复录像；CPU/PL 故障不自动重试。PL 失败后必须先检查并复位，再使用 DMA。本次没有更改 SD current、kernel、BOOT.BIN、init、flash 或 JTAG；摄像头永久自启动仍是待办，不能说已经交付。

## 标定与实拍测试

使用 camera_runtime/q12_calibration/camera_source.csv，SHA 为 9cbf9fdf9b4eed7f071e84f5d9ac005838709c9b5f696edcda5622a4ae19e21d。这是本只摄像头当前固定对焦位置下的 1280×720 原图内参；裁剪只减 cx160，不能套旧录像内参或载入旧场景地图。

物理板 Q12-25-1.5：12×9 方格、11×8 内角点、1.5mm 方格。40 张保留、36 张完整检测、单次质量筛选后35张通过；RMS 0.5673895px，最大单图1.2768808px。完整原始样本和筛选审计已提供；这只证明棋盘拟合，不是独立运动定位真值。

初次接手按实际新帧记录：S1 清图 → 有纹理且有远近层次的场景 → 缓慢平移产生视差 → 停稳 → 返回原视角。纯旋转、远景/平面或失焦需单独记录，不能将改阈值或隐藏 LOST 当修复。保持当前对焦；改变对焦后重标。

采集/解码30FPS、短驻留数据、仅1帧有效的近30FPS或 HDMI60Hz 都不是完整实拍30FPS。统计真实序号/时间戳、缺帧、有效率/状态、分项 CPU、RSS、延迟、HDMI/AXI错误，并在无效帧保持 pose_valid=false。
