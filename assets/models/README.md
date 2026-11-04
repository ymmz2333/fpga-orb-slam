# MiDaS Small QAT 模型

- `midas_qat_best.pth`：微调 QAT 状态，需要 Vitis AI 2.5 与项目的 QAT 模型构造。
- `midas_kv260_b4096.xmodel`：B4096 目标部署图；使用前检查硬件指纹。
- `placement.json`、`compilation.json`：保留的编译和算子放置记录。
- `MANIFEST.json`：文件大小、SHA-256 和来源索引。

上游 MiDaS 采用 MIT，原许可见 `../../LICENSES/MiDaS-MIT.txt`。
本目录不包含 AMD DPU IP、驱动或板卡位流。
当前完整使用说明见 `../../docs/submission/DEPENDENCIES_ZH.md`。
