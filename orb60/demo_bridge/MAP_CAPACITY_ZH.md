# 固定地图交接容量（2026-10-26）

本机源码已将两阶段交接容量提高至 **1,024 个关键帧、30,000 个可靠稀疏点**。
覆盖 RK `BridgeExport.h`、Python 地图包与预警、Zynq manifest 校验、
导入配置、固定地图运行配置及 SLAM 关键帧配置边界。每帧 PL 特征上限仍为 1000。

原有字节保护继续生效：传输单文件不超过 32 MiB（TCP 包还需留文件名空间），
地图包总计不超过 64 MiB，原生 `.zmap` 加载不超过 32 MiB。
因此点/关键帧数合格并不保证任意数量的观测都可接收；容量没有取消文件大小校验，
也没有自动丢点、抽关键帧或改变地图坐标。

本机验证：新目录 `orb60/build/demo_bridge/capacity_1024_30000/native`
编译通过；`test_controls` 与 `test_export_map` 共 5 项通过；
`test_map_capacity` 在合成的 30,000 点、1,024 关键帧、90,000 观测上验证
实际 C++ MapStore 导入、保存、加载及字节一致回存，并检查 30,001 点或
1,025 关键帧分别被 Python/C++ 拒绝，原发布地图指针不变。

复现（先用 build_native 在上述目录构建）：

```powershell
.venv/Scripts/python.exe -m unittest orb60.demo_bridge.tests.test_map_capacity -v
```

随后按用户“更新一下”的请求完成配套部署：RK 导出库、地图包校验和控制器已更新；
Zynq 当前版本为 `/opt/orb-demo/releases/demo_20261026_capacity_1024_30000`。
ARM 自检 `ALL_TESTS_PASS`，启动后 `hardware_verified=true`、
`hardware_fault=false`，模式 LOCAL；RK 报告 LOCAL_RELOCALIZING。
部署前后原地图指针逐字节一致。未改变 bitstream、内核或 BOOT 文件。
旧 Zynq 版本和 RK 旧导出库/程序均已保留。

证据位于 `orb60/build/demo_bridge/capacity_1024_30000/`：
`arm-selftest.log`、`arm-checks.json`、`BUILD_SHA256SUMS`。
尚未在板上安装满容量地图或测量其 ARM 内存峰值、定位吞吐与重定位延迟。
此前超限失败的建图没有完整保存，需重新建图。
