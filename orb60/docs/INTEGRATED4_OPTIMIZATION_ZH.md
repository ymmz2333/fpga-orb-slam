# 4PPC 整合优化：一次覆盖主要热点

2026-10-13，按用户最新要求扩大已确认方向，停止无限追加局部试验。
自定义 HLS负责像素/描述子数据通路，AMD IP继续负责DDR/仲裁/时钟/复位。
器件、算法、八层金字塔、特征预算、排序、16字节点及64字节特征保持原约束。
PS和实体板工作暂缓；用户已授权自主运行、诊断和继续长任务。

## 本轮结果与决策

| 方向 | 决策 | 本轮范围及依据 |
|---|---|---|
| 候选存储 | 保留并用于4PPC | 显式两bank锦标赛、八个score bank。两bank完整路由已省295 Slice/1627 LUT/16 DSP，无吞吐退化 |
| 内部位宽 | 扩大到相关热点 | 已证明moment21/CORDIC43/34；4PPC Resize采用精确相对3-bit索引/11-bit权重；比较32-bit patch组织。保留外部坐标/score完整范围 |
| 描述子预取 | 扩大组合 | 三种2/4/8预取各38精确RTL通过，最大217958→150534拍。8请求仅较2请求增加16个HLS LUT/8FF，先合入8；真实高延迟收益由整帧确认 |
| FAST时序 | 四lane统一拆级 | 实测最差13级FAST路径；bright/dark差分→min3→min9→response→16→8→4→2→1，每级明确边界 |
| CE/复位 | 暂停扩大 | 尚无测量支持全核改写，不加入新的统一CE/reset策略或时序例外 |
| 4PPC | 直接实现并验证 | 共享一次DDR读，FAST/NMS、Gaussian、Resize四像素流水，独立packed行缓存及完整背压 |

胜出的两bank+位宽版完整route `20261013_004602_orb_100mhz_d84b324e` 已SUCCEEDED：
WNS +0.388ns/WHS +0.033ns，TNS/THS0；28029 LUT、28335 FF、64.5 BRAM tile、
38 DSP、10080 Slice(87.27%)、1059控制集。相对两bank未缩宽版再省873 LUT/159 Slice。
这给出保留位宽方向的依据，不能替代4PPC新顶层的资源与时序结果。

## 实现及版本

现有m_axi64/地址32、寄存器位置和外部top名称 `fastv2_layer2_hls` 保留，构建参数
`LayerPpc=4` 选择完整新实现；统计版本为 **0x00600003**，识别4PPC。
旧版0x00600001计pair；新版同布局的 `*_pairs` 字段分别计source/blur quad及
Resize非空可变宽度packet。每个活动输出行，每个source quad产生一个1~4像素packet；
生成器全量验证这一性质，harness按新版本独立核对，不沿用旧pair计数。

- FAST七条32-bit/240深度行缓存及两条score行，窗口7×10；NMS3×6。
  四lane候选按原扫描顺序保序合并，每拍一个候选，所有mask0~15均可处理。
- Gaussian四组七tap计算，水平四个16-bit结果以64-bit传送，七条64-bit/240行缓存。
  保留原系数、最终舍入和reflect101；实际BRAM物理配置以综合/完整route为准。
- Resize一条32-bit/240上一行缓存；输出发射ROM用59bit表达四个相对index/weight和count，
  各层逐坐标验证原整数插值及round-to-even权重。跨行紧密64-bit打包支持1/2/3尾像素。
- 描述子结合moment/CORDIC位宽、独立read_request/receive actor和8个adapter读credit，
  raw/blur patch采用32-bit组织；一个64-bit接收拍做两个32-bit写，用真实双口BRAM。
  双缓冲及原moment→angle→BRIEF流水保留，错误排空和有效写回前缀保持原语义。

## 验收终点

主机阶段已通过FAST独立1e7随机ring及17408定向值、21层引擎精确事务、
38描述子精确事务；新增merge全部16mask/mixed各4096组及18个Gaussian形状，
覆盖行尾1/2/3/0、边界和guard。HLS必须重新通过各自Csim/综合/co-sim/IP及真实II。

随后并行执行一次完整顶层route和随机AXI→原生12帧共享DDR测试。测试使用相同
100MHz及四种DDR服务条件，保留40~60拍首读延迟的942点压力帧，统计实际AR/R、
outstanding、水位、等待和整帧时间。对已有第一阶段参照的时间差是4PPC+后端的
**组合收益**，因为两核RTL均改变；不单独归因于预取或位宽。

最终判断完整Slice/BRAM/DSP、setup/hold、TNS/THS、约束/DRC/路由及最大压力帧时间。
不以HLS资源估计之和宣称能装下，不继承旧WNS/旧周期或板上FPS。新的四候选
serializer还需独立RTL随机背压覆盖，最终通过前不发布bitstream。

复现入口：`scripts/hls.ps1 -Variant optimized -Kernel layer2 -LayerPpc 4 -FastStaged -Cosim`；
后端：`-Variant optimized -Kernel descriptor -DescriptorWidthMode 2 -DescriptorPrefetch 8 -DescriptorPatch32 -Cosim -DescriptorVectors <冻结vectors>`。
相邻门禁通过后用 `scripts/finish_integrated4.ps1 -Job <冻结整合job> -Mode Route/Frame`。
