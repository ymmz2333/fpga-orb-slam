# Zynq7015 板测与 SD 自启验收

主机时间2026-10-24，ACZ7015 / xc7z015clg485-2。程序已在板上独立运行，不依赖RK3588；电脑用于SSH控制和取回证据。本轮输入为SD上的原录像，摄像头仅预留接口。

## 当前程序与硬件

当前包`output/sd_ssh_20261024_001751.tar.gz`，SHA256 `d185da12676f8eab68bcbd27354329656cf4ce4d2cbacf98b3fe32cbbba8192d`。ARM二进制来自`build/arm_20261023_235849`，与已逐帧板测的包000018逐字节一致。板端`/opt/zynq-slam/current`指向该版本。

PL执行原配对ORB和HDMI_2扫描，PS Cortex-A9执行匹配、P3P/位姿优化、有限关键帧稀疏建图和UI。原交接包缺少完整RK3588 ORB-SLAM3/UI源码，这里为新实现；不包含完整Atlas、全局Sim3回环、视觉惯性或稠密重建。

Vivado2018.3最终产物为`../.work/z18/20261023_194328/final_20261023_201146`。完整顶层WNS+0.015ns、WHS+0.013ns、66068/66068网全路由；Slice11523/11550，LUT36777、FF38422、BRAM73.5、DSP44。ORB150MHz，像素74.25MHz/串行371.25MHz；内部覆盖、CDC和Gray skew通过。四个序列化TMDS外部边界没有PCB/接收器延迟模型，已单独列出。详见PL_BUILD_ZH.md。

## 完整2273帧物理链路

使用960×720原始GRAY8，真实PL ORB，PS建图/定位/UI，HDMI_2 1280×720p60。导入2547个固定锚点，实际新增453点，容量3000点/16关键帧。

| 测试 | 全链路平均FPS | 有效位姿帧 | 峰值RSS MiB | 输入丢帧 / HDMI欠载 / AXI错误 |
| --- | ---: | ---: | ---: | --- |
| 黄金记录逐字节验证，恢复间隔3 | 30.7633 | 2063/2273 | 12.7422 | 0 / 0 / 0 |
| 对照：恢复间隔5 | 30.9096 | 2060/2273 | 12.6641 | 0 / 0 / 0 |
| 第一次SD重启，首轮导入原地图 | 30.5220 | 2053/2273 | 12.5898 | 0 / 0 / 0 |
| 同次自启第二轮，加载已保存地图 | 30.6248 | 2058/2273 | 12.6094 | 0 / 0 / 0 |

采用恢复更及时的间隔3：正常跟踪逐帧执行；连续三次全局恢复失败后每3帧尝试一次，其间保持LOST无效。黄金测试的2273帧数量及全部64字节ORB记录一致，帧身份连续，全部2273帧提交HDMI。300帧滚动窗口、步长30帧，最低30.171759FPS；HDMI扫描约60.0055Hz。377帧超过33.33ms，因此这是平均及窗口吞吐结果，不是每帧硬截止期保证。

同录像原SLAM有2081个有效参考帧，共同有效2060（98.99%覆盖）；在原地图坐标中不对齐比较，位置误差中位0.001893、P95=0.006255单目世界单位，旋转P95=0.557006度。该数据来自同录像参考，不是独立真实尺度真值。对任意新场景从零建图的长期质量尚未验收，不能外推这些结果。

应用另使用原保留DDR中的16MiB工作窗口，RSS不包括MMIO映射。原SD设备树512MiB reserve/no-map布局保留，不能把应用RSS当成整机总内存占用。默认服务的点、关键帧、队列、轨迹均有界，磁盘保留最近三轮；验收归档另存。

原始证据`output/zslam-final-bench-000700.tar.gz`，SHA256 `5c329b3ea062a808bafa31e6ff5e911fae111455a5ed108dbfe9c636ad808f52`；已在本机核对并解包至`output/final_bench_000700/`。`scripts/analyze_run.py`生成逐阶段、滚动吞吐和位姿诊断，原始run/display/timing/trajectory均保留，不修改应用级NOT_VERIFIED字段。

## UI 与功能检查

本机及板上ARM自测通过：几何/离群点/退化、空地图初始化/跟踪/丢失恢复、有界地图、CRC及版本1兼容、固定锚点保存与继续建图、FIFO顺序/EOF/取消/异常、原始文件截断拒绝、摄像头回调所有权。UI全部371712个灰度预览像素核对，右向视锥测试通过；点云缓存与移动视锥/重置清空后的完整重绘逐像素一致。

右侧投影的左右基向量已修复。左侧绿色点是当前帧ORB角点，不是有固定ID的持久轨迹点；消失和重新出现属于检测结果变化。LOST时不显示伪造有效位姿。界面明确标注RECORDING / RELATIVE SCALE。

SSH实际测试start/stop/status/localization/mapping/save/reset；保存生成新的map-帧号.zmap，reset后实际点数与关键帧变0。随后恢复经过验证的非空3000点地图并继续运行。原数据和已保存验收地图未被覆盖。

## SD 启动与操作

已通过SSH执行SD安装及重启。首次boot_id从`10cdb116-7cdc-4819-9e61-59d1f2c54205`变为`05e87aff-a7be-4a2a-9d16-fd1c455503d1`；静态新设备树直接产生UIO，configfs无overlay，wc1模块自动绑定，SysV自动启动服务，SSH恢复。最新脚本更新的再次重启及含循环维护的吞吐另附取回证据。

最新版再次SD重启boot_id为`e47fc3a5-bf78-43d4-9280-225abc4c4125`，current=001751，wc1/三个映射地址正确、无configfs overlay、服务自动运行。连续三整轮各2273帧，CYCLE区间13.09→87.93、87.93→163.68、163.68→238.43秒，包含地图加载/保存/循环维护；对应30.3715、30.0066、30.4080FPS，合计6819帧/225.34秒=30.26094FPS。三轮有效帧2049/2059/2057，RSS12.53～12.75MiB，均0丢帧/0欠载/0AXI错误。

SD安装、两次重启、控制、地图与逐轮日志证据在`output/sd-boot-evidence-20261024.tar.gz`，SHA256 `f747964bea6168abcc12fc152b03d444c1fb0058fbf28a4eb67d478dcf0953f8`，已核对并解包到`output/sd_boot_20261024/`。现场服务留在板上持续运行。该30FPS版本作为基线保留，后续60FPS优化独立进行，不将目前结果写成已达60FPS。

uEnv选择版本独立目录中的配对bit/DTB，使用加载后的filesize，执行run sdboot，不执行saveenv。原BOOT.BIN、zImage、system.bit、system.dtb哈希保持一致；首次uEnv备份沿更新链保留。原备份在`output/zslam-sd-original-20261023.tar.gz`，SHA256 `696f525d92eac48b21a26fb8235bfc864bdf46301abb68f22a2f9d566b932fd5`。恢复命令与细节见SD_SSH_ZH.md；未使用JTAG、未写flash。

正常服务不导出每轮整幅截图，也不额外睡眠一秒；每轮仍保存地图、轨迹、计时与扫描计数。CYCLE行用uptime记录包含启动/地图加载/保存/维护的整个循环。板载RTC重启后返回2021默认日期，目录加入boot_id避免重名，性能计时使用单调时钟。

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.233
sh /opt/zynq-slam/current/scripts/zslamctl.sh status
sh /opt/zynq-slam/current/scripts/zslamctl.sh localization
sh /opt/zynq-slam/current/scripts/zslamctl.sh mapping
sh /opt/zynq-slam/current/scripts/zslamctl.sh save
```

物理HDMI点云画面已由用户在同版PL上确认；再次重启后的实屏自动恢复确认仍待用户回复，软件端的自启、提交和扫描计数分别核对。
