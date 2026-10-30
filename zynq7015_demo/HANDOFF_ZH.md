# 当前源码交接入口（2026-10-24）

已整理到本工作区的 `../handoff/zynq7015_usb_slam_20261024/`，同名 ZIP 为可传递交接包。请先阅读包根 `README_ZH.md`，运行 `python verify_handoff.py` 核对逐文件 SHA 和原构建输入关系；归档回执位于同名 `.verification.json`，ZIP 的 SHA 在 `.zip.sha256`。

说明模板保存在 [handoff_docs/README_ZH.md](handoff_docs/README_ZH.md)，包含代码索引、构建/核验、板端交接和未完成工作。重复导出使用 `python tools/export_handoff.py --output NEW_DIRECTORY`；输出目录必须不存在且位于本源码目录外。该命令只复制、哈希和压缩，不编译、不连接板卡。

当前主程序对应 `build/arm_20261024_180124`，S1 工具对应 `build/s1_controls_20261024_192801`，PL 对应 `final_20261023_201146`。本次新增的是交接文档及 Python 导出/完整性核验工具，未修改 ARM/RTL 算法源码。

USB/HDMI/S1 有历史实机验证；**持续整机30FPS及实拍跟踪鲁棒性尚未验收，频繁LOST未解决**。不是原RK3588完整ORB-SLAM3的等效移植。22:25物理网口断开，未重新确认板端当前状态，19:58断点的进程号为历史值。

保留原 `zynq_slam`、冻结基线、vendor 原件和 SD 发布包。原启动配置未改，摄像头临时模块/持续模式不会在重启后自动恢复。最新用户要求仅显示真实摄像头，不能直接执行会播放录像或恢复旧服务的历史基准脚本。
