# 外部 ORB 特征文件 v1（接口草案）

同一输入帧按整数纳秒命名：normal/<timestamp_ns>.orb、initialization/<timestamp_ns>.orb。
所有整数字段小端；浮点为 IEEE-754 binary32，小端。无隐含 C/C++ padding。
文件 = 64 字节头 + point_count 个 64 字节记录；不允许额外尾字节。
坐标对应送入 Frame 的第0层图像，未去畸变；Frame 后续执行去畸变。
FPGA 不必直接拼文件：电脑/Zynq PS 适配器可填充头部和派生信息，但不得静默改变语义。

## 文件头

| 偏移 | 字段 | 类型 | FPGA 要求 / 精度草案 |
|---:|---|---|---|
| 0 | magic=ORBFEAT + 0字节 | 8 bytes | PS填固定魔数 |
| 8 | version=1 | u16 | PS填；版本不符拒绝 |
| 10 | header_bytes=64 | u16 | PS填 |
| 12 | record_bytes=64 | u16 | PS填 |
| 14 | role：0正常，1初始化 | u8 | PS可由请求携带；FPGA须满足对应特征预算 |
| 15 | flags=0 | u8 | 保留，必须为0 |
| 16 | timestamp_ns | u64 | 必须绑定真实输入帧；PS用原始整数时间戳填，禁止由double秒回算 |
| 24 | width | u32 | 处理图像尺寸；PS填，须与实际图像相符 |
| 28 | height | u32 | 同上 |
| 32 | point_count | u32 | 实际输出点数，必须提供 |
| 36 | nLevels | u32 | 必须与配置/真实 octave 相符；单尺度设1 |
| 40 | scaleFactor | f32 | PS从配置填；与层尺度完全一致 |
| 44 | extractor_nFeatures | u32 | 请求预算；正常1000、初始化5000（B1基准） |
| 48 | descriptor_bytes=32 | u32 | 固定 |
| 52 | coordinate_space=0 | u32 | 0=第0层未去畸变像素；其它值拒绝 |
| 56 | monoLeft | i32 | 兼容原版特征排列/重叠区计数；PS可推导，必须保留点与描述子原始对应顺序 |
| 60 | reserved=0 | u32 | PS填0 |

## 每点记录

| 偏移 | 字段 | 类型 | FPGA 要求 / 精度草案 |
|---:|---|---|---|
| 0 | x | f32 | 必須提供。可由整数/定点经PS无歧义转换；定点位数/舍入规则待负责人确认；B1保持原版float位模式 |
| 4 | y | f32 | 同上；高层坐标必须先换算第0层 |
| 8 | octave | i32 | 必须提供或单尺度PS填0；范围0…nLevels−1 |
| 12 | angle（度） | f32 | 必须提供；B1保存连续原值；8档可转换为0/45/…/315，但其匹配影响只能在B2另测，负责人确认 |
| 16 | size | f32 | PS可由31*层scale推导；B1保留原版值；窗口大小/层尺度待确认 |
| 20 | response | f32 | 点选择分数要有明确语义；B1保留FAST response，FPGA打分/位宽待确认 |
| 24 | class_id | i32 | 通常−1，PS可填；B1完整保存以免破坏KeyPoint等价性 |
| 28 | reserved=0 | u32 | 固定0 |
| 32 | descriptor | 32 bytes | 必须提供全部256位；字节内bit顺序必须与ORB逐bit对齐，禁止只交换整数端序 |

头和记录的保留位、尺寸、role、时间戳、层数、尺度、特征预算、坐标、浮点有限性均校验；缺失或不匹配文件报错退出，不回退到native。
Frame 的各层scale/sigma²仍从按YAML构造的提取器读取，inject不生成图像金字塔或执行特征提取。

## 字节一致性验收

dump同时保存每帧两套结果，不仅保存当时被Tracking选中的一套。
另保存 memory/<role>/<timestamp_ns>.bin：从内存KeyPoint字段和描述子直接赋值的64字节记录快照。
协议写入采用显式小端字段编码；内存快照是另一条独立路径，限定IEEE float32/小端主机并检查结构大小。
独立Python程序解析头和每点字段，并逐字节对照内存快照，同时校验文件覆盖/roles/维度/尺度；验收不能只看点数或哈希。
这些内存快照仅用于B1验收，未来FPGA无需输出。

## 计时语义

native：保持提取算法原样。dump：额外提取另一套并写盘，不纳入正式耗时比较。
inject：单独记录文件读取和解码/验证耗时；TrackingTimeStats的ORB ext槽位此时是整个特征读取路径，不能叫“ORB算法耗时”。
理想剩余耗时按正常帧逐帧 Total−特征槽位计算，再统计中位数/均值/P95；它不包含真实FPGA传输成本，也不是全系统吞吐量保证。
正式对比native/inject同一752×480/1000/8配置并固定CPU与DMC；旧A3动态DDR参考单独标注。
