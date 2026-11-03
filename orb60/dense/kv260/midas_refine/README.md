# MiDaS 独立量化优化

本目录及 `orb60/build/kv260/midas_refine/` 是侧会话的独立实验范围。主会话正在测试的 FastDepth、原有 MiDaS 权重、原量化产物和验收报告不被覆盖。

实验容器仅可写上述结果目录，工程其余部分只读。容器限制为 2 个 CPU、4 GiB 内存，使用已经固定的 Vitis AI 2.5 镜像，无网络。不连接任何板卡。

## 实验类型

- `experiment.py`：固定配置敏感性诊断、量化范围、偏置和截断统计。16 位诊断不能部署到本轮 DPUCZDX8G。
- `calibrate.py`：排除冻结验收集的原始视频帧编号，用剩余 82 个保存的真实关键帧重新校准；分别检查众数和保守范围统计。
- `finetune.py`：用户于本次会话明确允许后，从原权重初始化，通过官方 Vitis AI 2.5 AdaQuant 做逐层参数微调，生成独立的新权重。它不是完整的端到端 QAT 训练。
- `qat_model.py`、`qat_train.py`：等价改写 SAME padding、加法和插值为 Vitis AI 2.5 需要的显式模块；20 张浮点改写检查后进行真正的端到端 INT8 QAT。保留两处独立的无参数 ReLU 实例，避免量化器错误复用；原始推理数值保持一致。
- `summarize.py`：生成本实验自己的结果汇总，不改主会话总报告。

四处 align_corners 和最终 half_pixel 上采样保留原语义。输出仍为 RGB/ImageNet NCHW 输入对应的相对逆深度。评估采用原数值公式，不做事后尺度、偏移或 min/max 对齐。

## 运行

在 WSL 工程根目录：

```bash
bash orb60/dense/kv260/midas_refine/launch.sh --case saturation
bash orb60/dense/kv260/midas_refine/launch.sh calibrate --statistic modal --mode calib
bash orb60/dense/kv260/midas_refine/launch.sh calibrate --statistic modal --mode test
bash orb60/dense/kv260/midas_refine/launch.sh finetune --training-frames 4 --mode fit
bash orb60/dense/kv260/midas_refine/launch.sh finetune --training-frames 4 --mode test
bash orb60/dense/kv260/midas_refine/launch.sh qat-train --epochs 4
```

`fit.json` 保存训练帧编号、输入哈希、权重来源及真实状态；`test.json` 保存 20 张逐张验收。训练使用原浮点网络作为逐层目标，不使用验收样本训练。数据仍来自同一录像，不能据此声称跨场景泛化。

逐层微调完成后，对 82 张训练侧关键帧重新校准；独立 test 进程重新载入实际保存的参数，再运行冻结验收集。必须同时满足原门槛：每张 NRMSE ≤ 3%、Spearman ≥ 0.98。

端到端训练进一步将这 82 张分为 70 张训练、12 张内部验证；仅用内部验证选择 best.pth，原 20 张用于最终门槛。冻结 BN 统计，原浮点输出作为蒸馏目标，不拟合输出的尺度或偏移。best.pth 是训练框架权重，不能直接送入 DPU；先通过 to_deployable 转换后的 20 张数值检查，再判断是否导出目标模型。每轮保存 latest.pth 供恢复，失败结果仍完整保留。

命令入口将运行脚本读入内存再执行，避免运行期间编辑脚本导致执行偏移。旧探针和首次逐层训练后验证启动失败的日志保留；已保存参数可直接通过 test 入口复验，无须重跑训练。

`QUANTIZATION_PASS` 仅表示电脑量化参考满足数值门槛，后续还须通过目标编译、算子分配和真实板端验证。任何探针/API 错误及失败参数均保留，不重标为成功。

`RESULTS.md` 和 `summary.json` 是目前已完成实验的汇总；仍为 RUNNING 的训练不在其中冒充结果。
