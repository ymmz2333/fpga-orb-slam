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

PS 版本：`/opt/orb-demo/releases/demo_20261026_handover_quiescent`。
源码容量上限保留 1024 关键帧、30000 稀疏点。
旧发布包及原 `/etc/init.d/zynq-slam` 保留；仅取消旧录像服务的 SysV 自动启动链接。
安装前的 init、链接清单、地图指针、boot_id 和 SD 固件哈希保存在
`/opt/orb-demo/acceptance/autostart-<boot_id>/`。

恢复旧录像开机启动时，先停止 `orb-demo`，取消指向 `../init.d/orb-demo` 的 SysV
链接，再依据上述备份恢复旧 `S99zynq-slam` / `K01zynq-slam` 链接。不得同时运行两者。
安装脚本不主动重启；实际重启验收结果另保存在本机 `sd_autostart_acceptance.json`。
