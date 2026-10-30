# 阶段 D：HDMI 可视化演示

日期：2026-10-03。A3 未启动，等待用户看完屏幕后确认。

## 已完成与验收

- A2 提交关系：cf36b06 = d307c3c + 0008；相对官方 v1.0-release 的补丁为 0001～0008。
- A2 报告、汇总 CSV、分状态汇总和本次全部结果图明确标注 600×350 官方非等比缩放；不与未来 A3 752×480 混用。
- D0：GNOME / GDM 桌面存在；cat 的本地 X11 会话 c1 活跃；DISPLAY=:0，XAUTHORITY=/run/user/1000/gdm/Xauthority。HDMI-1 为 1920×1080@60 Hz。
- glxinfo：Mesa 21.2.6，llvmpipe (LLVM 12.0.0, 128 bits)，Accelerated:no，实际为软件渲染。direct rendering:Yes 不表示硬件加速。
- D1：GTK 插件加载成功，Map Viewer 与 Current Frame 都显示并更新；窗口已并列。用户亲眼确认“两个窗口正常，画面流畅”。
- 实际 affinity 为 CPU0～7，没有绑核；三个 governor 运行前后均为 interactive，未修改。
- 正常显示这次记录 3682 个输入帧。视频停止后，用户要求立即结束；向本次 mono_euroc PID 81196 发送 SIGTERM，进程已关闭。退出码 -15，如实保留，不能称为正常退出。
- D2：四张中文 300 dpi PNG 由已接受的 A2 raw 数据生成；核对 ATE 与原结果一致；实际 PNG DPI 元数据为 299.9994。已传至板上 ~/demo/figures/ 并在 HDMI 全屏打开。
- A2 分析 / ATE 的 10 项单元检查通过；绘图脚本从 raw 重算通过，选中的 ATE 中位运行是 attempt_01（2.3212543 cm）。

## 实际 CPU 样本

本次演示启动后的 tracking_or_shutdown 阶段共 245 个一秒样本：CPU 均值 232.04%，中位数 237.43%；100% 表示一个逻辑核。
均值相当于八核整机容量的 29.01%。该区间包含停播与退出等待，属于粗略演示占用，不是纯跟踪计算基线。
原始 cpu.csv、metadata.json 保存在 completed-viewer/，板上原路径 ~/demo/20261003T130039-viewer/。

## 问题与处理

最初演示失败：OpenCV 4.5.5 编译时 WITH_GTK=OFF，cvNamedWindow 报“function is not implemented”。失败日志保留在 failed-viewer/。
已确认 HIGHGUI_ENABLE_PLUGINS=ON，采用同一 OpenCV 官方源码提供的 GTK3 独立插件，只编译 window_gtk.cpp；没有重编 ORB 或整套 OpenCV。
经用户选择后安装 37 个新增开发包，零升级：下载 13,649,908 字节，每个包按板上 apt 元数据 SHA256 校验；包清单、安装与构建日志已保留。
插件单独输出 install-demo/lib，只有 demo_viewer.sh 设置其加载环境；实验 install/lib 不变。ORB 二进制 SHA256 与 A2 一致。
依赖安装加插件配置 / 编译这次实际用时 43.69 s（不含之前下载传输），作业 exit 0，GTK 3.24.20。
板上 DNS 下载仍失败；本次由电脑 HTTPS 下载后走局域网传输。
OpenGL rockchip 驱动仍报加载失败，使用 llvmpipe 完成演示；没有改动 GPU 驱动。
停播后窗口进程仍存活，按用户要求终止。日志显示当前地图已无关键帧，演示轨迹未保存；演示不做 ATE，也不替代 A2 数据。

## 文件与复现

实时入口：scripts/demo_viewer.sh；独立 YAML：demo/EuRoC_demo.yaml。
插件构建：scripts/build_gtk_plugin.sh；可校验的依赖解析 / 下载：scripts/gtk_packages.py。
CPU / governor 记录：scripts/monitor_demo.py；窗口排列：scripts/arrange_demo_windows.py。
结果图入口：scripts/plot_a2_demo.ps1 和 plot_a2_demo.py；显示入口：scripts/show_figures.sh。
新增 raw/groundtruth_cam0.tum 为 A2 已验证的相机真值，支持不依赖 runtime 的重算。
完整操作见 docs/D_REPRODUCE.md。全部代码在 d/hdmi-demo 分支按功能提交。
演示日志、计时、轨迹没有加入 runs.csv 或实验汇总。

## 下一步

用户确认 D 后再开始 A3 六组配置各五次、按序号交错执行；监测无风扇散热，一旦发现 A76 降频暂停批次并报告。
