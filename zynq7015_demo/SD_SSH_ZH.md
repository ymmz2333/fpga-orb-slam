# SD 启动、SSH 与 HDMI_2 使用

目标 ACZ7015 / xc7z015clg485-2，Vivado 2018.3。板上 ARMv7 Linux 4.14.0-xilinx #52，SD p2 为根分区，p1 为 FAT 启动分区。手册默认 root@192.168.1.233:22；本轮已按现有主机密钥验证并连接。旧 Dropbear 仅对该次 SSH/SCP 启用 `HostKeyAlgorithms=+ssh-rsa`，不关闭主机密钥检查。密码不写入脚本。

本轮摄像头不接入，输入使用原录像导出的 960×720 GRAY8。画面标为 RECORDING；每帧真正通过 PL ORB，PS 执行匹配、P3P/位姿优化、稀疏建图和 UI。HDMI_2 为 1280×720p60 TMDS/DVI，无音频。该软件是新实现，原交接包没有完整 RK3588 ORB-SLAM3/UI 源码；不宣称已完整移植 ORB-SLAM3。

## 文件与数据

`bin/zynq-slam`、`bin/test-zslam` 使用 SDK 2018.3 GCC 7.3.1 / Cortex-A9 / NEON / hard-float。静态链接 C++/GCC 运行库，动态 libc/libm/libpthread；板上 ABI 与自测分别检查。BSD P3P 子集的许可证随包放在 licenses/。

`firmware/s_wrapper.bit` 与 `.bit.bin` 来自同一已验收 DCP，HDF 内嵌 bit 逐字节一致。Bootgen 2018.3 输出已核对负载换序及 NOP 对齐；未重建或覆盖原 BOOT.BIN/内核。`hardware/system.dtb` 从原 DTB 修改，仅关闭冲突旧 PL 设备、旧 DDR alias，新增共享 UIO；89 个已有节点做过语义核对。

共享 UIO map0=0x43c00000/64KiB（HDMI 控制+0x8000），map1=0x43c10000/64KiB，map2=0x20000000/16MiB。控制映射是 Device，DDR 为唯一 WC 映射；原内核模块匹配 #52，不强制加载模块。两个 RGB565 槽在 0x20b00000/0x20d00000，各预留 2MiB，与 ORB 和 RX 工作区逐项检查无冲突。

原始录像 /opt/zynq-slam/data/video_inputs_20261023/gray8.bin 已通过所有灰度 SHA-256 校验。原地图在同目录 handoff_map_20261023/。黄金参考在 arm_replay_20261023_195434/，只用于诊断；正式运行不必读取它。

## 加载、运行与控制

`sh scripts/board_inventory.sh` 为只读检查；`board_software_check.sh` 校验包并运行 CPU 自测，不访问 PL。`load_hdmi_board.sh` 检查 PS 配置、保留内存与哈希，依次解绑旧消费者，RAM 加载新 PL，应用 overlay，绑定原 WC 模块。该步骤不会改 SD 启动选择。当前本轮 RAM 加载及物理点云显示已经确认成功。

```sh
sh scripts/load_hdmi_board.sh
./bin/zynq-slam --raw /opt/zynq-slam/data/video_inputs_20261023/gray8.bin \
  --uio /dev/uio0 --hdmi-uio /dev/uio0 --calibration config/camera_handoff.csv \
  --import-map /opt/zynq-slam/data/handoff_map_20261023 \
  --max-points 3000 --max-keyframes 16 --frames 2273 --output /tmp/NEW_RUN
```

`--loc-only` 固定地图定位；默认允许增加新点。导入点为固定锚点，不移动、不替换、不重写描述子，新点独立优化。`--verify-golden GOLDEN` 对每帧物理 ORB 的数量和 64 字节记录逐字节核对，遇到差异立即停止。`--serial` 用于与默认有界流水线对比。两个队列各容量2，顺序与身份不变，不通过跳帧提高计数；采集/ORB建议CPU1，SLAM/UI建议CPU0，是否实际应用写入 run.json。

正常局部跟踪逐帧执行。连续三次全局重定位失败后，默认每三帧尝试一次全局重定位，避免相似的无匹配画面重复占用全部 CPU；其间保持 LOST 和无效位姿。`--relocalization-interval 1` 恢复逐帧全局尝试，范围1至30；调度可能延迟重新获得定位，必须同时查看轨迹有效覆盖。计时 CSV 记录 recovery_attempted，run.json 记录间隔。全局描述子检索采用近似哈希候选，之后执行完整 Hamming、比值和几何检验；它可能漏掉候选，不与 PL ORB 字节一致性混为一谈。

部署 current 后，SSH 控制：

```sh
sh /opt/zynq-slam/current/scripts/zslamctl.sh start
sh /opt/zynq-slam/current/scripts/zslamctl.sh status
sh /opt/zynq-slam/current/scripts/zslamctl.sh localization
sh /opt/zynq-slam/current/scripts/zslamctl.sh mapping
sh /opt/zynq-slam/current/scripts/zslamctl.sh save
sh /opt/zynq-slam/current/scripts/zslamctl.sh reset
sh /opt/zynq-slam/current/scripts/zslamctl.sh stop
```

start 通过 FIFO 接收控制，首轮导入原地图，后续优先加载上轮保存的地图。录像结束后立即开始下一轮，保留最近三轮完整输出；每轮有轨迹、计时、地图、扫描计数和日志。正常自启不导出整幅截图，避免循环间额外停顿；需要时使用 `ZSLAM_SNAPSHOT=1 sh scripts/zslamctl.sh start`（先停止已有服务）。/run/zynq-slam-service.log 的 CYCLE 行用内核 uptime 记录整轮开始/结束，含地图加载、保存与维护，供计算循环整体吞吐。reset 清空当前地图转为从零建图，不能把导入地图定位质量外推为任意新场景建图质量。

地图新格式版本2保存固定点标志，仍支持读取版本1。CRC 错误、相机标定不一致或超出容量均拒绝加载，不替换活动地图。单目是相对尺度；原录像借用标定不适用于新摄像头的精度承诺。

板载RTC当前在重启后返回2021年的默认日期，目录日期沿用板上时钟；目录名另外包含内核boot_id，避免不同次开机同名。测量使用单调时钟/uptime，验收文件关联主机实际时间和boot_id，不以板载RTC作性能计时。

## SD 安装与恢复

原 SD 文件备份在本机 output/zslam-sd-original-20261023.tar.gz。install_sd_boot.sh 需要本轮 physical-io-verified 记录：它表示已核对物理 I/O，不替代30FPS/轨迹验收。安装将 bit/DTB 放在 FAT 的新 zynq-slam/RELEASE/ 目录，保留原 system.bit/system.dtb/BOOT.BIN/zImage，最后切换 uEnv.txt。新 uEnv 使用加载后的 filesize，并执行 run sdboot，不执行 saveenv。rootfs 安装 SysV 启动脚本和 current 链接；脚本自身不重启板卡。

更新本工程自己的已安装包前先停止服务。安装器核对已有init和运行级链接属于本工程，保留当前启动选择为uEnv.previous.txt，并沿用首次工厂备份uEnv.original.txt；不会覆盖未知init。不同包的bit/DTB各存独立目录，current与uEnv切换后按实际重启另验收。

恢复可运行该包 scripts/restore_sd_boot.sh，或在另一台电脑上将 uEnv 的 bit/DTB 选择恢复为 FAT 根目录的原文件。恢复脚本保留 SD 启动选择并去除 saveenv，不自动重启、不写 flash、不使用 JTAG。

## 验收口径

记录 actual run.json、timing.csv、trajectory.csv、display.json；run.json 中的 NOT_VERIFIED 保留为应用级声明，独立板测结论另写验收文件。HDMI 60Hz扫描不能代替30帧新内容；LOST帧保持无效位姿。并行阶段耗时有重叠，不应相加作为帧周期，另有等待和端到端延迟。验收须包括完整输入、逐字节 ORB 校验、整链路持续吞吐、内存、位姿覆盖/误差、0欠载/0AXI错误、SD重启后SSH和实际画面。
