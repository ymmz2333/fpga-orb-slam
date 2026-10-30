# 共享黄金模型层数决策轮的运行预检

本轮以 orb_frontend_golden/decision/HANDOFF_TO_OTHER_CHAT.md 为范围：G1 的
native/V0/L8/L4/L2/L1 × 三个全序列 × 五次，共90槽位。旧150次矩阵、MIN、
强制丢失不在本轮。用户要求先核对P1/P2/P3，并授权继续补齐新链路预检。

P1：板上FAILED保留，电脑压力测试SKIPPED_BY_USER，不作硬件通过声明。
PC0构建SUCCEEDED只能证明构建完成，不能替代以下运行证据。

本轮新增均为PS/电脑监督和核验软件，不实现PL、不改SLAM后端。
代码在pc/golden-layer-precheck分支；实际验收只读取新state与原始日志。

1. 实际 run_pc_slam 监督器运行多线程受控卡住进程；保持正式120秒无完成帧
   上限，验证保留三个完整CSV状态行、全线程gdb栈、各线程wchan/status，
   且捕获先于SIGINT。只给子进程PR_SET_PTRACER_ANY，不修改全局Yama设置。
2. 独立native构建复用已有build_slam.sh。规范源与scratch的src/include逐文件
   归一化行尾比较，示例仅允许0012的八行日志flush变化；算法不变。
3. 两段Tello前150帧，正常与初始化全部字段/描述子：实际Frame dump与
   corrected独立原版提取器逐字节比对，再以这些原版包回放，逐帧核对整数
   时间戳、实际role、特征数和调用数。两条role轨迹若不一致则停止诊断。
   独立Frame核验提取器使用与当前SLAM相同的-march=native/-fPIC、Release/O3
   和OpenCV4.5.5前缀。PC0早期生成器未启用-march=native，仅保留为诊断，
   不能把两个编译选项不同程序的浮点BRIEF旋转差异称为随机内存损坏。
4. 三数据集各前150帧生成G1五候选两档，校验头/尺度/预算/role；五候选均
   用真实B1注入路径跑150帧，检查逐帧日志的timestamp/role/count和零提取器
   调用。是否初始化属于正式B3结果；未初始化不替换候选，但流程失败会阻止启动。

V0是G1整数控制，含数值合同变更，不要求与native字节等价。原版dump回放
验证和G1候选验证分别记录；不把旧PC1/P2/MIN门禁标为通过。本预检不替代90次结果。

Windows golden_layer_worker.py 持有临时防待机请求和高性能电源模式；先构建、
再预检，通过才调用已有launch_decision.py，以新编号启动原90槽位脚本。
任何预检失败停止，不生成伪造的90行实验结果。完成/失败恢复电源并释放防待机。
Windows协调器只自动读取状态以维持生命周期，不回传运行日志；Agent启动确认后
结束对话、不持续轮询。最终FINISHED_AWAIT_LAYER_DECISION，用户选层数后才更新v1.0。
