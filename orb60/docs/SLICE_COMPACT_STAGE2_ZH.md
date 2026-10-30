# Slice 专项第二轮：压紧锦标赛与 BRAM 换 LUTRAM

2026-10-13。按用户要求与方向矩融合独立推进。实现选择自定义HLS；
只修改独立实验副本 `experiments/slice_compact`，不改变当前发布源码或
正在执行的融合任务快照、脚本与控制接口。器件015、960x720、8层、
原特征预算、四路像素、精确选点与记录、64bit AXI/32bit地址不变。

## 实测依据与候选

已交付4PPC125完整top的Slice11437/11550(99.02%)，控制集1127。
最差路径是锦标赛BRAM读到写数据，WNS+.167ns；7级逻辑、逻辑3.267ns、
布线4.200ns。原树每节点49bit，重复保存41bit点和8bit cell。

| 模式 | 树节点 | 八个局部点存储 | 用途 |
|---|---|---|---|
| 1 |38bit score8/y11/x11/cell8排序键|原LUTRAM|先隔离比较/选择逻辑修改|
| 2 |36bit score8/y10/x10/cell8排序键|原LUTRAM|固定几何范围收紧与存储打包|
| 3 |同模式2|BRAM|用现有BRAM余量交换LUTRAM/选择布线|

排序键从高到低为score、反向y、反向x、反向cell，无效节点为0。
unsigned max精确实现score降序、y/x升序及完全同分低cell优先；
输出再从原best_low[cell]取完整41bit载荷，tile不被删除或截断。
两bank真实依赖及BuildTournament II=2保留，不使用false dependency。
固定profile的有效点x<=927/y<=687，10bit足够；Csim先检查原11bit
坐标范围再构造窄键，未更改合法性判断。未来1080p必须重新核定位宽。

## 验收与测量边界

每个候选独立运行百万随机/定向key对拍和原67项sorted-grid测试，
覆盖same-cell、revisit、同分、预算、空点、容量错误和guard；
再与冻结21个layer事务的独立Python/golden进行Csim、综合对照。
检查实际八个score bank II1、建树II2、38/36bit两bank、LUTRAM/BRAM
映射、图像流水II1和四个AXI64/address32，不把pragma当作实现证据。

模式2/3随后从各自冻结probe重建C/RTL/IP、完整II门禁，并各做125MHz
完整routed top，固定使用已交付2730a8cf后端以隔离图像核Slice收益。
两候选的失败证据分别保留；不修改Vivado策略、Pblock或时序例外。
该轮仅方向性资源/时序验收，尚不能替代新核随机AXI、共享DDR整帧、
与融合后端的组合路由或新bitstream交付。板测和PS继续暂缓。

入口：`scripts/slice_compact_experiment.ps1`。所有路径从统一环境推导。
三候选使用同一冻结作者快照，无基线重跑。长任务启动后告知PID并
结束该轮，按用户最新要求不自动轮询，待用户通知再检查结果。

## 当时的阶段检查（模式3运行中）；最终结果见下节

用户通知后单次检查：主32312仍存活，模式3路由包装进程29076仍存活，
子任务 `20261013_140252_orb_125mhz_bbfaee64` 终态尚为RUNNING。
不把模式2完成当作整个实验完成，不自动继续轮询。

三种模式各1000300组key排序对拍与67项原sorted-grid通过；
21项精确CSim/综合、真实bank/II/key-width/storage门禁通过。
HLS层核估计相对原层核：模式1 -601LUT/-135FF；模式2 -560LUT/-141FF/
-2BRAM18；模式3 -696LUT/-213FF/+14BRAM18，DSP均不变。

模式2 freshC/RTL/IP `20261013_131233_layer2_slice2_03e05c30` 及完整路由
`20261013_132932_orb_125mhz_829043c3` 已SUCCEEDED。固定旧2730a8cf后端：

| 指标 | 已交付4PPC125 | 模式2 | 差值 |
|---|---:|---:|---:|
| LUT |35551|34919|-632|
| FF |36122|35972|-150|
| BRAM tile |74|73|-1|
| DSP |44|44|0|
| Slice |11437(99.02%)|11380(98.53%)|-57|
| 控制集 |1127|1113|-14|
| WNS/ns |+.167|+.248|+.081|
| WHS/ns |+.015|+.027|+.012|

TNS/THS0、setup/hold/pulse失败0，完整约束/路由/严格DRC和200路径/
50网络诊断通过。最差已换到PS控制写宽度寄存器，1级7.504ns；
还观察到数据流enable2770负载、量化搜索CE和FAST路径，后续从这些
真实热点选择局部控制候选。仅释放57Slice，尚未解决高占用问题。
模式2新图像核随机AXI、共享DDR整帧和与融合后端的组合路由仍未验收。
暂不根据这一个候选定最终选择，待模式3结果后比较；不生成新bit。

## 最终结果与保留决定

实验57e7d94f最终SUCCEEDED/DIRECTIONAL_ROUTES_COMPLETE。模式3的
bbfaee64也通过完整125MHz路由，WNS+.260ns/WHS+.037ns、TNS/THS0。
实际34748LUT/35708FF/81BRAM/44DSP/11465Slice(99.26%)、1142控制集。
尽管LUT减少，Slice比发布版增加28、比模式2增加85，BRAM比模式2增加8。
因此保留模式2，拒绝模式3作为后续候选；模式3是功能/路由通过但资源目标
更差，不记作测试失败。两轮仍固定旧后端，不冒充与融合后端的联合证据。

用户随后要求自主推进、优先尽可能提高可完整路由主频，无需告知进程号。
新频率探索合并模式2与已通过的方向矩融合；在测得的量化反馈搜索、
PS控制写入长路径上分别采用精确HLS整数流水和AMD AXI-Lite寄存器切片。
高频时钟由AMD Clocking Wizard从100MHz PS FCLK产生，所有HP/GP/PL
同步使用同一输出时钟。重新生成每档RTL，不通过旧周期缩放估计收益。
