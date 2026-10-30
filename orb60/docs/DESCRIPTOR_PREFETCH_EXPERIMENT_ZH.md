# 描述子跨行预取有界实验

2026-10-13。实现选择为自定义 HLS，保留现有 AMD AXI/DDR；无新 DMA，PS 暂缓。
性能依据为第一阶段高首读延迟压力帧 28.91/30.84 ms、patch 端口实际 outstanding
最多2且平均很低，详细证据见 `ARCHITECTURE_STAGE1_FRAME_RESULTS_ZH.md`。
本轮不重跑旧基线，不直接扩展4PPC或BRIEF端口。

`DescriptorPrefetch=0` 保留原指针/memcpy装行，默认行为不变。实验值2/4/8采用
`hls::burst_maxi<uint64_t>`，分别配置 patch AXI adapter 的未完成请求数；实际统计
须在随机 AXI 和原生整帧中重新测量，不能把配置值当作观察值。

每个 patch 读口只有一个请求发出 actor 和一个接收 actor：

- `issue_raw_requests` / `issue_blur_requests` 提前发出逐行 `read_request`。
- 点元数据先写深度2 FIFO，再发该点请求；接收 actor 可立即推进，不依赖请求
  actor 全部完成。adapter 的有限请求队列为发出端施加背压。
- `load_raw` / `load_blur` 在独立 DATAFLOW actor 里按原行/word顺序 `read()`，
  接收循环要求II=1，继续使用原 raw/blur 块双缓冲及所有权。
- 原合法性检查在请求前执行；空点、非法点及越界 blur 行不发请求，所有已发请求
  都有对应读取。首个错误后的点和块继续排空，保持相同的有效写回前缀。

请求的地址和 word 数与原 memcpy 完全相同：raw每行4/5个64位word、blur按
原裁剪/对齐取数。没有扩大patch范围或改变统计字节。m_axi各端口继续64位、
地址32位，生成控制寄存器逐项与原版比较；4KB边界和最终写响应在协议门禁验证。

实现参考本机2024.2的 `hls_burst_maxi.h` 和
[AMD手动突发说明](https://docs.amd.com/r/2024.1-English/ug1399-vitis-hls/Using-Manual-Burst)。
请求发出与接收可以位于不同 DATAFLOW actor；不能在同一串行actor里先排入任意多
请求、再接收，否则有限请求队列可能死锁。主机功能adapter只有所有权/请求平衡
模型，不证明有限credit或RTL背压。

初步主机检查通过已有独立golden的38项精确对拍，覆盖全部方向、追加、空点、
非法控制/点、错误前缀及256点。结果为 `build/optimized/comparison/prefetch_functional_check/result.log`。
HLS入口 `scripts/descriptor_prefetch_experiment.ps1` 顺序运行2/4/8的C仿真、
综合、Verilog co-sim和IP导出，保持相同源码/向量。它检查独立发出/接收actor、
真实循环II、实际adapter参数、寄存器映射和HLS资源/RTL周期；没有整帧或路由结论。

通过后优先比较相同DDR条件下的随机AXI/原生整帧，尤其40~60拍首读延迟的942点
压力输入，记录实际AR数量、平均/最大outstanding、有效传输、等待和逐层周期。
只有实测整帧降低才保留该方向；最后再与已通过的内部位宽方案组合并完整路由。
