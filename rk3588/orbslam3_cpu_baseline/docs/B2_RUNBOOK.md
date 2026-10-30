# B2运行入口

板上项目根目录，前提是已验收C1/OpenCV4.5.5。

```bash
bash scripts/build_b2_candidates.sh
python3 scripts/prepare_b2.py --output runtime/b2/development_config
python3 scripts/check_b2_real_images.py
```

配置和检查目录不能覆盖复用。全新环境先建立原A1/B1/C1验收程序；B2只编独立工具，不调用主工程build.sh。

电脑端测试：

```powershell
. ..\..\scripts\project_env.ps1
& $ProjectPython -m unittest discover -s scripts -p test_b2_tools.py
& $ProjectPython -m unittest discover -s scripts -p test_c_tools.py
```

后台B2，批次名必须唯一：

```powershell
rk start 'python3 scripts/batch_b2.py --batch B2_design_smoke_01 --cooling-note "heatsink; no running fan"' -Name b2-smoke
rk exec 'python3 scripts/check_b2_started.py --batch B2_design_smoke_01' -Name b2-start-check
```

首次出现OK后停止查询，等用户回来验收。SSH或HDMI桌面终端人工查询：

```bash
cat ~/orbslam3_cpu_baseline/runtime/b2/B2_design_smoke_01/batch_state.json
```

FINISHED才表示批次完成；THERMAL_PAUSE/ERROR_PAUSE需要诊断，不重新提交同名任务。用户确认完成后电脑端运行：

```powershell
. ..\..\scripts\project_env.ps1
& $ProjectPython scripts/finish_b2.py --batch B2_design_smoke_01 --download
```

只先取状态；RUNNING就退出，不轮询。完成后下载单个归档，核对raw_manifest的SHA256，保留原始字节，再生成冒烟/单元/FAST CSV和B3时长预测。几GB特征库留板上corpus目录。

B3的batch_b3.py/evaluate_b3.py本轮不执行。批准后才传--approved-round-one。强制丢失只有提案，没有实现；全帧库容量需在B2报告估算并核对剩余空间。

## 2026-10-05 输入故障后恢复

用户批准先继续B2。保留原来的B读取失败和MIN不完整特征库，仅追加两个唯一目录的input_recovery01验证；已有28次不重跑。完整输入SHA256预检通过后复用B的已校核特征，MIN重新生成到新目录，再完成两段全帧FAST。

```powershell
rk start 'python3 scripts/resume_b2.py --batch B2_design_smoke_01 --cooling-note "heatsink; no running fan"' -Name b2-input-recovery
rk exec 'python3 scripts/check_b2_started.py --batch B2_design_smoke_01 --folder flight_20261004T200648_509768_918b85a4__B__input_recovery01' -Name b2-recovery-check
```

批次计划变为32条记录（30个原槽位，含两处失败，加2个恢复验证）。CSV不覆盖失败记录；预测全帧生成量时按数据集/候选去重，排除不完整生成与复用特征导致的重复计数。继续保持B3未启动。
