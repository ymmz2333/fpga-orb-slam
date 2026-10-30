# D：HDMI 演示和 A2 结果图复现

所有演示日志、轨迹、计时文件只放在板上 `~/demo/`；不加入实验 CSV。
实验 YAML 和 install/lib 不变。演示 YAML 单独位于 demo/EuRoC_demo.yaml，
跟踪仍为官方非等比缩放 600×350，只加大了 Viewer 点大小和关键帧线宽。

## GTK 插件

现有 OpenCV 4.5.5 的 WITH_GTK=OFF，但 HIGHGUI_ENABLE_PLUGINS=ON。
采用它官方源码中的独立 GTK3 插件，仅编译 window_gtk.cpp，输出 install-demo/lib。
Linux 插件按官方实现从主进程解析 OpenCV 符号；无需重链接 ORB-SLAM3。
demo_viewer.sh 只为演示设置 OPENCV_CORE_PLUGIN_PATH 和 OPENCV_UI_BACKEND=GTK3。
未修复 Mali/rockchip GPU 驱动；实际 OpenGL 为 llvmpipe 软件渲染。

板上 DNS 下载失败时，先取得实际 apt 依赖和 SHA256：

```powershell
rk exec 'python3 scripts/gtk_packages.py manifest ~/demo/gtk-packages' -Name gtk-manifest
scp rk3588:demo/gtk-packages/packages.json runtime/gtk-packages/
```

电脑端加载根目录 scripts/project_env.ps1 后，用 `$ProjectPython` 执行：

```powershell
& $ProjectPython scripts/gtk_packages.py download runtime/gtk-packages
scp runtime/gtk-packages/* rk3588:demo/gtk-packages/
rk exec 'sudo -n dpkg -i ~/demo/gtk-packages/*.deb > ~/demo/gtk-packages/install.log 2>&1 && bash scripts/build_gtk_plugin.sh > ~/demo/gtk-packages/build.log 2>&1' -Name gtk-plugin
```

本次 apt 解析为 37 个新增包、零升级，实际包版本及校验值在 demo/gtk-packages.json。
另一台机器应重新解析；包版本已变化、下载失败或安装冲突时停下来报告，不强行忽略错误。

## 实时演示

```powershell
rk exec 'bash scripts/demo_viewer.sh' -Name hdmi-demo
rk status <返回的 job_id>
rk wait <返回的 job_id> -Seconds 30
```

脚本设置 DISPLAY=:0 和当前用户的 GDM Xauthority、会话环境。
保持 mono_euroc 原来的时间戳等待，不用 taskset，不写 governor。
monitor_demo.py 留存 CPU 样本、实际 affinity、运行前后 governor 和退出码；
100% CPU 表示一个逻辑核，除以八才是全机 CPU 容量占比。
TrackingStates 写入有缓冲，观测到的行数只用于粗略区分启动阶段；最终总帧数以关闭后的文件为准。
arrange_demo_windows.py 用 X11 窗口管理器消息将两个窗口并列，仅移动演示窗口。
流畅度由屏幕观看确认，不能用截图替代动态观察。

## 结果图

在电脑端项目目录运行：

```powershell
.\scripts\plot_a2_demo.ps1
scp demo/figures/* rk3588:demo/figures/
rk exec 'bash scripts/show_figures.sh' -Name demo-figures
```

四张 300 dpi PNG 由 reports/a2/MH01_600x350_passive_01/raw 重新计算产生。
groundtruth_cam0.tum 是 A2 已验证的相机坐标系真值；计算 Sim3，逐次核对已验收 ATE。
轨迹和耗时图选五次 ATE 中位的 attempt_01；构成图取五次正常帧 sum(ORB)/sum(Total) 的中位数。
Total 含内部 Image Resize；构成图的其余部分包含这项开销。
manifest.json 记录所有输入哈希、图像哈希、字体、分辨率及所选运行。
需要 Microsoft YaHei、SimHei 或 Noto Sans CJK SC 中文字体，缺字体会明确失败。
图片查看器全屏打开有序列表，用左右方向键切换，Esc 退出全屏。

D 阶段验收后等用户确认再进入 A3。
