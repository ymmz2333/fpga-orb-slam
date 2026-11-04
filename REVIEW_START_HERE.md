# 源码审阅入口

1. [系统与代码导航](README.md)
2. [源码、工具版本和构建流程](docs/submission/SOURCE_AND_BUILD_ZH.md)
3. [依赖和模型](docs/submission/DEPENDENCIES_ZH.md)
4. [第三方与开源许可](THIRD_PARTY_NOTICES.md)

重点沿 USB 图像 → ZYNQ-7015 硬件 ORB → KV260 建图/DPU/点投影/融合 → 地图交接 →
ZYNQ-7015 PS 定位链检查。控制器包含手动结束、自动交接、换线重连、重启和保存地图持久化。
原 2026-11-03 审阅说明保存在 `docs/submission/REVIEW_SNAPSHOT_20261103.md`。
当前整理版本的文件清单由 `SOURCE_SNAPSHOT_SHA256.json` 绑定。
