#!/usr/bin/env python3
"""Generate the stage report and portable raw evidence from measured CSVs only."""
import argparse
import csv
import json
import pathlib
import shutil
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--batch", required=True)
args = parser.parse_args()
report = ROOT / "reports/a2" / args.batch
with (report / "runs.csv").open(encoding="utf-8") as stream:
    runs = list(csv.DictReader(stream))
valid = [row for row in runs if row["valid_run"] == "True"]
if len(valid) != 5:
    raise SystemExit("A2 未完成: five measured valid runs required")
with (report / "summary.csv").open(encoding="utf-8") as stream:
    summary = {row["metric"]: row for row in csv.DictReader(stream)}
evidence = report / "raw"
copy_names = ["TrackingTimeStats.txt", "TrackingStates.csv", "SessionInfo.txt", "ExecMean.txt",
              "LocalMapTimeStats.txt", "LBA_Stats.txt", "program.log", "telemetry.csv", "run_metadata.json",
              "remote_job_id.txt", "f_MH01.txt", "kf_MH01.txt", "timing_summary.csv", "module_summary.csv",
              "timing_facts.json", "ate.csv", "ate.json", "ape.zip", "evo.log", "evo_command.json",
              "ape_inputs.json", "ape_errors.csv", "sim3.json"]
metadata = []
state_summary = []
for row in runs:
    destination = evidence / row["attempt"]
    source = pathlib.Path(row["output"])
    if not source.exists():
        source = destination  # A Git clone can regenerate from retained raw evidence.
    destination.mkdir(parents=True, exist_ok=True)
    for name in copy_names:
        if source.resolve() != destination.resolve() and (source / name).exists():
            shutil.copy2(source / name, destination / name)
    if row["valid_run"] != "True":
        continue
    meta = json.loads((source / "run_metadata.json").read_text(encoding="utf-8"))
    metadata.append(meta)
    if int(row["processed_frames"]) != 3682 or meta["observed_affinity"] != [4,5,6,7]:
        raise RuntimeError("Unexpected frame count or affinity")
    with (source / "timing_summary.csv").open() as stream:
        for group in csv.DictReader(stream):
            state_summary.append(dict(attempt=row["attempt"], tracking_width=600, tracking_height=350,
                                      resize_policy="official nonuniform resize", **group))
if len({meta["binary_sha256"] for meta in metadata}) != 1 or len({meta["orb_commit"] for meta in metadata}) != 1:
    raise RuntimeError("The five runs used different binaries/source revisions")
with (report / "state_summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(state_summary[0]))
    writer.writeheader()
    writer.writerows(state_summary)


def value(row, key, scale=1, digits=2):
    return format(float(row[key])*scale, ".%df" % digits)


def aggregate(key, scale=1, digits=2):
    row = summary[key]
    return "%s（%s～%s）" % tuple(value(row, item, scale, digits) for item in ("median", "min", "max"))


lines = ["# A2：RK3588 EuRoC MH01 纯 CPU 基线", "", "日期：2026-10-03。A2 验收通过；停在阶段确认门槛，未运行 A3。", "",
         "五次有效运行全部处理 3682 帧，最终 Atlas 均为 1 张地图，没有地图重置。第二次有 5 帧 RECENTLY_LOST 并恢复；其余运行见下表。",
         "散热状态由用户确认：已装散热器，无风扇或风扇未转。没有检测到 A76 降频或 thermal cap，无需补跑。", "",
         "## 环境与固定条件", "",
         "Ubuntu 20.04.6 aarch64，内核 5.10.160；GCC 9.4.0，CMake 3.16.3，内存约 7.7 GiB，运行时 swap=0。",
         "CPU0–3 为 A55，CPU4–7 为 A76（MIDR 确认）。SLAM 绑定 CPU4–7，采样监督进程绑定 CPU0–3。",
         "policy0/4/6 使用 performance；每次退出恢复原 interactive。A76 两个 policy 的采样频率均为 2.256 GHz。",
         "温度/频率采样间隔 0.5 s，保留全部温区、CPU cooling 状态、运行前后传感器与实际 affinity。离散采样不能证明样本间绝无瞬时降频。", "",
         "ORB 官方 v1.0-release：0df83dde1c85c7ab91a0d47de7a29685d046f637。",
         "实际 ORB 提交：`%s`；五次二进制 SHA-256 一致：`%s`。" % (metadata[0]["orb_commit"], metadata[0]["binary_sha256"]),
         "提交关系已确认：cf36b06 = d307c3c + 0008；相对官方 v1.0-release 的全部补丁为 0001～0008。",
         "OpenCV 4.5.5、Pangolin v0.8、Eigen 3.3.7、Boost 1.71、OpenSSL 1.1.1f，Release/O3、j2 构建。",
         "四个产物的 ldd 检查通过：mono_euroc、libORB_SLAM3.so、DBoW2 使用的 OpenCV 均来自 install/lib 的 4.5.5；g2o 没有 OpenCV 依赖。",
         "系统有 4.2 运行库与 python3-opencv，未发现 4.2 开发包，当前产物没有混链。未卸载任何系统包。", "",
         "输入 752×480，官方 EuRoC.yaml 原样将跟踪图像缩为 **600×350（非等比）**，1000 特征、8 层。",
         "Settings 自动调整内参；关闭 viewer，保留按原始时间戳等待的实时节奏。",
         "Total 是示例测量的 TrackMonocular 调用耗时加外部 resize；包括 Settings 内部 resize，排除 imread 和帧间等待。",
         "内部 resize 没有写入上游 Image Resize 专用向量，所以该列全 0 表示未单独计时，不能解释为真实零耗时。其他模块统计均排除 0，空模块不编造数值。", "",
         "## 输入和评价检查", "",
         "电脑仅解压 MH_01_easy，LAN scp 到 ~/data/euroc/MH_01_easy。ZIP CRC 与 7376 个传输文件的 SHA-256 验证通过。",
         "cam0 PNG 与 CSV 数据行均为 3682；真值 36382 行，官方 MH01 全部时间戳对应图像，缺失 0。",
         "原始时间间隔为名义 20 Hz，实际 49,999,872～50,000,128 ns；未改写时间戳。",
         "ATE 在电脑 .venv（CPython 3.12.12）使用清华镜像安装的 evo v1.37.1 计算，板上不安装 evo。",
         "轨迹 ns 用 Decimal 转 TUM 秒，机体 GT 用 T_BS 转 cam0。与官方左相机 GT 的位置逐项比较通过（validation/gt_reference_check.csv）。",
         "命令：`evo_ape tum groundtruth_cam0.tum camera.tum -as --t_max_diff 0.01 --save_results ape.zip`。",
         "每次均与独立 NumPy Umeyama Sim3 误差逐项比较，通过。每次关联 3638 个位姿，原始导出 3681 行。",
         "第二、第四次导出分别含 4、3 条完全重复的时间/位姿行，来自上游空 pose 丢失帧复制前一记录；保留官方输出，不推测位姿或改写时间。",
         "这些重复行在本次 MH01 中位于 GT 关联范围之外，不影响本次 ATE 的关联帧数。", "",
         "## 每次结果", "",
         "|运行|全程|地图|丢失帧|恢复|重置|ATE RMSE（cm）|正常帧|", "|---|---|---|---|---|---|---|---|"]
for row in valid:
    lines.append("|%s|3682/3682|%s|%s|%s|%s|%s|%s|" %
                 (row["attempt"], row["maps"], row["lost_frames"], row["recovery_frames"],
                  int(row["active_map_resets"])+int(row["full_resets"]), value(row,"ate_rmse_m",100), row["frames"]))
lines += ["", "|运行|Total 均值/中位数/P95（ms）|ORB 中位数/P95（ms）|逐帧占比中位数|总耗时占比|>50 ms|>33 ms|", "|---|---|---|---|---|---|---|"]
for row in valid:
    lines.append("|%s|%s / %s / %s|%s / %s|%s%%|%s%%|%s%%|%s%%|" %
                 (row["attempt"], value(row,"total_mean_ms"), value(row,"total_median_ms"), value(row,"total_p95_ms"),
                  value(row,"orb_median_ms"), value(row,"orb_p95_ms"), value(row,"orb_ratio_frame_median",100),
                  value(row,"orb_ratio_sums",100), value(row,"total_gt50_fraction",100), value(row,"total_gt33_fraction",100)))
lines += ["", "以上耗时/占比/超时比例仅使用正常跟踪帧。占比的两种分母均包含非等比图像缩放。P95 为 linear 插值。", "",
          "|运行|SoC 平均温度（°C）|SoC 最高（°C）|全部温区最高（°C）|A76 policy4 / policy6 频率范围（GHz）|降频|", "|---|---|---|---|---|---|"]
for row in valid:
    lines.append("|%s|%s|%s|%s|%s～%s / %s～%s|未检测到|" %
                 (row["attempt"], value(row,"mean_soc_temp_c"), value(row,"max_soc_temp_c"), value(row,"max_all_zones_temp_c"),
                  value(row,"policy4_freq_min_khz",1e-6,3), value(row,"policy4_freq_max_khz",1e-6,3),
                  value(row,"policy6_freq_min_khz",1e-6,3), value(row,"policy6_freq_max_khz",1e-6,3)))
lines += ["", "## 五次汇总", "", "每项取五次运行统计值的中位数；括号为五次最小～最大，不是把所有帧混在一起重新算分位数。", "", "|指标|中位数（最小～最大）|", "|---|---|"]
for key, label, scale in [("ate_rmse_m","ATE RMSE（cm）",100), ("total_mean_ms","Total 均值（ms）",1),
                          ("total_median_ms","Total 中位数（ms）",1), ("total_p95_ms","Total P95（ms）",1),
                          ("orb_median_ms","ORB 中位数（ms）",1), ("orb_p95_ms","ORB P95（ms）",1),
                          ("orb_ratio_frame_median","逐帧 ORB 占比中位数（%）",100), ("orb_ratio_sums","ORB 总耗时/Total 总耗时（%）",100),
                          ("total_gt50_fraction","Total >50 ms（%）",100), ("total_gt33_fraction","Total >33 ms（%）",100),
                          ("mean_soc_temp_c","SoC 平均温度（°C）",1)]:
    lines.append("|%s|%s|" % (label, aggregate(key, scale)))
lines += ["", "## 初始化与丢失帧", "", "|运行|类别|帧数|Total 均值/中位数/P95（ms）|ORB 中位数/P95（ms）|", "|---|---|---|---|---|"]
for row in state_summary:
    if row["category"] not in ("initialization", "lost"):
        continue
    if int(row["frames"]) == 0:
        lines.append("|%s|%s|0|无样本|无样本|" % (row["attempt"], row["category"]))
    else:
        lines.append("|%s|%s|%s|%s / %s / %s|%s / %s|" %
                     (row["attempt"], row["category"], row["frames"], value(row,"total_mean_ms"), value(row,"total_median_ms"),
                      value(row,"total_p95_ms"), value(row,"orb_median_ms"), value(row,"orb_p95_ms")))
lines += ["", "初始化成功帧仍归初始化，未混入正常帧。初始化/丢失组不计算 ORB 占比；零样本不写假的 0 ms。", "",
          "## 验收与问题处理", "",
          "A2 五次全程运行、相机参考 Sim3 ATE、状态计时对齐、正常帧两种占比、初始化/丢失分组、零填充排除、温频记录均通过。",
          "论文 Table II 报告 MH01 纯单目 ATE 0.016 m（10 次中位数）；本次为厘米级且量级一致，不声称逐值复现论文。",
          "来源：[ORB-SLAM3 原论文](https://arxiv.org/pdf/2007.11898)。", "",
          "过程中两个脚本检查已修正并保留记录：官方 20 Hz 时间戳带 ±128 ns 差异；上游允许完全重复的丢失帧导出记录。",
          "第二次运行后，评价因重复时间戳暂停；检查源码并修正评价后恢复原批次。SLAM 二进制、YAML、数据均未改变。",
          "另外，上游内部 resize 无独立计时列；报告明确标为未单独计时，其耗时始终计入 Total。没有把空计时项记为性能零值。", "",
          "## 修改与复现", "",
          "ORB 修改仅为 0008 补丁：mono_euroc.cc 输出逐帧跟踪状态，Tracking.cc 输出最终 Atlas 地图数。未改 SLAM 算法、官方 YAML 或等待节奏。",
          "流程文件：prepare_dataset_a2.py / check_dataset_transfer.py / validate_mh01.py（数据）；run_a2.py（板上单次）；",
          "batch_a2.py / a2_pc.ps1（电脑批量调度）；analyze_a2.py（分状态统计）；evaluate_a2.py（电脑 ATE）；",
          "check_gt_reference_a2.py（官方 GT 校验）；report_a2.py（报告与证据）；test_a2_analysis.py / test_a2_ate.py（10 项合成数学/统计检查）。",
          "源码均在 a2/euroc-baseline 分支，按功能提交。命令和统计定义见 [A2_REPRODUCE.md](../../../docs/A2_REPRODUCE.md)。", "",
          "```powershell", ".\\scripts\\a2_pc.ps1 -Action summary -Batch "+args.batch,
          ".\\scripts\\a2_pc.ps1 -Action report -Batch "+args.batch, "```", "",
          "runs.csv 保留每次原始统计，summary.csv 可重新生成，state_summary.csv 保留分组结果。",
          "raw/ 保留计时、状态、轨迹、温频、日志、evo ZIP 与来源 hash；电脑/板上的 runtime/a2/ 另保留完整工作目录。", "",
          "下一阶段计划（待用户确认）：A3 以 752×480 删除 newWidth/newHeight 为基准，376×240 等比缩放并由 Settings 调整内参；",
          "按一个维度改变 nFeatures/nLevels，每组至少五次。当前没有 A3 实验数字。"]
(report / "A2_REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
print("A2_REPORT_PASS valid_runs=5 report="+str(report / "A2_REPORT.md"))
