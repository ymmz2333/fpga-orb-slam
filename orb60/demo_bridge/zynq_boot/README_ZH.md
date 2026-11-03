# 7015 摄像头定位：SD 开机启动

此配置将已验证的 PS 软件固定在 Linux SD 根文件系统中。使用现有
`4PPC / 150 MHz ORB + HDMI` 配套硬件，不重新生成或覆盖 BOOT.BIN、
内核、bitstream、设备树及 uEnv.txt。

开机由 SysV `S99orb-demo` 启动 `/opt/orb-demo/boot/start_camera.sh`：

1. 校验启动脚本及 WC / UVC 模块 SHA256。
2. 绑定原 WC UIO 驱动，加载已验证的摄像头模块，等待摄像头最多 30 秒。
3. 调用 `/opt/orb-demo/current/run_zynq.sh`，校验 PS 发布包，使用 USB 实时输入。
4. 从 `/opt/orb-demo/maps/current` 选择已校验的本地地图；彩色稠密点用于环境显示，
   稀疏点及关键帧用于定位。没有有效地图则等待建图操作。

摄像头缺失、PL 或地图失败会明确报错；不回退到录像/CPU ORB，不自动重试 PL 故障。
本地定位不依赖 RK 或电脑。当前地图有效不代表任意相机位置都能成功重定位。

板端管理：

```sh
/etc/init.d/orb-demo status
/etc/init.d/orb-demo stop
/etc/init.d/orb-demo start
tail -20 /run/orb-demo-service.log
```

当前板端启动修复版本：`/opt/orb-demo/releases/demo_20261101_startup_v1`。
它沿用 `demo_20261026_handover_quiescent` 的全部二进制和标定，只更新
`run_zynq.sh`；原版本保留。配套 boot 目录为
`/opt/orb-demo/boot-20261101-startup-v1`，只修正 `start_camera.sh`。
源码容量上限保留 1024 关键帧、30000 稀疏点。
旧发布包及原 `/etc/init.d/zynq-slam` 保留；仅取消旧录像服务的 SysV 自动启动链接。
安装前的 init、链接清单、地图指针、boot_id 和 SD 固件哈希保存在
`/opt/orb-demo/acceptance/autostart-<boot_id>/`。

恢复旧录像开机启动时，先停止 `orb-demo`，取消指向 `../init.d/orb-demo` 的 SysV
链接，再依据上述备份恢复旧 `S99zynq-slam` / `K01zynq-slam` 链接。不得同时运行两者。
安装脚本不主动重启；实际重启验收结果另保存在本机 `sd_autostart_acceptance.json`。

## 2026-11-01：重复开机离线修复

板上没有 RTC，开机时钟会回到 2021 年。旧脚本以时间戳加 PID 命名运行目录；
两者在重复开机时都可能相同，`mkdir` 因旧目录已存在而退出，TCP5601–5604
随之全部不可用。摄像头仍被识别，RK 的 FPGA 地址配置也正确。

`run_zynq.sh` 改为 boot ID 加 `mktemp -d` 原子分配独立目录，不覆盖旧记录，
不依赖 RK 或联网校时。`start_camera.sh` 按实际内核模块目录
`/sys/module/videobuf2-vmalloc` 检查，避免服务重启时重复 insmod 退出。

板端 BusyBox 下固定时间与 PID 的 32 次目录分配、一次服务重启、两次实际软件
重启均通过；每次重启后检查了新的 boot ID、自动启动、摄像头处理记录增长和
真实 FPGA 状态。固件、地图指针和原发布目录的校验保持一致。本轮未执行断电冷启动。
完整日志和回退位置见 `orb60/build/demo_bridge/startup_repair_20261101/`。
