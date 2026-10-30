"""Generate the C0 report from audit CSVs, frame-quality evidence and provenance."""
import argparse
import csv
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def read_csv(path):
    with path.open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,default=ROOT/'reports/c0')
    a=p.parse_args(); out=a.report
    rows=read_csv(out/'inventory.csv'); stats=read_csv(out/'timestamp_stats.csv')
    events=read_csv(out/'timing_events.csv')
    acceptance=json.loads((out/'acceptance.json').read_text(encoding='utf-8'))
    reference=json.loads((out/'reference_intrinsics.json').read_text(encoding='utf-8'))
    stat_by={(r['clip'],r['clock']):r for r in stats}
    fmt=lambda x: f'{float(x):.3f}'
    lines=['# C0 数据盘点与 OAFD 临时内参候选','',
        '本阶段选择 PS/电脑软件完成元数据、时间戳和码流检查；不修改 FPGA/ORB 算法，不运行 SLAM。',
        'B1 已完成；B2 等实拍数据正式标定和数据集选择。C0 后按用户要求停下确认工作分辨率与时间戳方案。','',
        '## 验收与原始数据保护','',
        f'- 数据盘点状态：`{acceptance["status"]}`。这表示审计流程完成并发现数据警告，不表示跟踪或标定通过。',
        f'- {acceptance["clips"]} 段、{acceptance["files"]} 个原始文件，合计 {acceptance["source_bytes"]} 字节；原始 SHA256 前后相同。',
        '- 原始文件已设置只读属性，SHA256 逐文件见 source_manifest.csv；解码和所有处理在 runtime/c0/source_copy 副本进行。',
        '- 原始 packets.h264 和 codec_headers.h264 均保留。九段原始 VCL 图像切片与 MP4 内切片的顺序和字节哈希完全相同；排除封装/SPS/PPS 差别，证明所审计 MP4 没有二次编码。',
        '- 7/9 段包含被解码器标记为 corrupt 的帧（合计 16 帧）；一段另有 20 个编码包没有解码帧输出。不能把解码器未标 corrupt 的其他帧断言为没有压缩/传输伪影。',
        '- 原始保护是只读属性与哈希审计，并非不可撤销的访问控制。','',
        '## 视频清单','',
        '全部为 MP4 / H.264 Main，960×720，标称 30 fps，无 B 帧。实际帧率必须注明时间轴口径。',
        'MP4 PTS 来自录制软件的固定 30 fps 封装；PC 解析/就绪帧率使用侧车单调时钟，不能当作相机曝光帧率。',
        '视频码率为 ffprobe 的视频流平均码率；接收负载码率为录制窗口内 H.264 字节数×8/窗口时长，不含网络协议开销。','',
        '| 片段 | 编码包/离线解码帧 | MP4时长(s) | 录制窗口(s) | 解码PTS帧率(fps) | PC解析/就绪帧率(fps) | 视频/接收负载码率(Mbps) | 预录包 | corrupt帧 | 无解码输出 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f'| {r["clip"]} | {r["raw_vcl_packets"]}/{r["mp4_total_frames"]} | {fmt(r["mp4_duration_s"])} | {fmt(r["capture_wall_s"])} | {fmt(r["mp4_decoded_fps"])} | {fmt(r["pc_parser_fps"])}/{fmt(r["pc_ready_fps"])} | {float(r["mp4_video_bitrate_bps"])/1e6:.3f}/{float(r["received_payload_bitrate_bps"])/1e6:.3f} | {r["preroll_packets"]} | {r["corrupt_decoded_frames"]} | {r["encoded_packets_without_decoded_frame"]} |')
    lines += ['', '## 时间戳来源与间隔','',
        '- `video.mp4`：编码包 PTS=DTS=包序号，time_base=1/30，duration=1；由电脑封装时重写。编码包间隔恒为约 33.333 ms；解码失败时解码帧 PTS 可留下空缺。',
        '- `packets.jsonl:t_parser_emit`：电脑 perf_counter，H.264 解析器输出 AVPacket 的时间，既不是相机采集时刻，也不是 UDP recvfrom 的原始接收时间。',
        '- `frames.jsonl:t_ready`：同一电脑解码并转换 BGR 完成的时间，还包含解码/转换延迟。',
        '- `tag` 是关联计数器，不是相机硬件帧号；无可信相机曝光时间戳。解析与解码在同一进程，不能把所有间隔突增归因于网络。',
        '- 预录 IDR 历史有 3–27 个包，时间早于 capture.started；应保留用于解码参考，不把它们当作丢帧。正式 SLAM 输入是否排除预录帧等待确认。',
        '- 下表是 PC 解析出包时间：P50/P05/P95/P99/max 均为 ms。>50 ms、≥100 ms 是诊断门槛，不等价于已证明的相机掉帧。', '',
        '| 片段 | P05 | P50 | P95 | P99 | max | >50ms次数 | ≥100ms次数 | 最长间隔位置(s) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        s=stat_by[(r['clip'],'pc_parser_emit')]
        es=[e for e in events if e['clip']==r['clip'] and e['clock']=='pc_parser_emit' and e['interval_ms']]
        longest=max(es,key=lambda e:float(e['interval_ms'])) if es else None
        location=fmt(longest['start_relative_s'])+'–'+fmt(longest['end_relative_s']) if longest else '无超过50ms事件'
        lines.append('| '+r['clip']+' | '+' | '.join(fmt(s[k]) for k in ('p05_ms','median_ms','p95_ms','p99_ms','max_ms'))+f' | {s["gap_gt50ms"]} | {s["stall_ge100ms"]} | {location} |')
    lines += ['', '完整位置与两种 PC 时钟间隔分布分别见 timing_events.csv 和 timestamp_stats.csv；事件位置从该时钟首条记录计时，解析时钟包含预录帧。不同 clock 的事件不可相加当作独立掉帧次数。', '',
        '## 解码异常位置','', '| 片段 | corrupt离线帧索引（0起） | 对应MP4解码PTS(s) | ffprobe关键日志 |','|---|---|---|---|']
    decode_notes=[]
    for r in rows:
        quality=read_csv(out/'raw'/r['clip']/'frame_quality.csv')
        bad=[f for f in quality if f['corrupt']=='True']
        log=(out/'raw'/r['clip']/'ffprobe.log').read_text(encoding='utf-8',errors='replace').splitlines()
        # FFmpeg context addresses vary: preserve original logs, show bounded diagnostic text.
        excerpt='；'.join(line.split('] ',1)[-1] for line in log[:2]).replace('|','/') or '无警告'
        lines.append(f'| {r["clip"]} | '+', '.join(f['frame_index'] for f in bad)+' | '+', '.join(fmt(f['mp4_pts_s']) for f in bad)+f' | {excerpt} |')
        missing=int(r['encoded_packets_without_decoded_frame'])
        if missing:
            omissions=[e for e in events if e['clip']==r['clip'] and e['event']=='encoded_packet_no_offline_decoded_frame']
            gaps=[e for e in events if e['clip']==r['clip'] and e['clock']=='mp4_decoded_frame_pts' and e['interval_ms']]
            largest=max(gaps,key=lambda e:float(e['interval_ms']))
            clocks=json.loads((out/'raw'/r['clip']/'clock_reference.json').read_text(encoding='utf-8'))
            start=float(omissions[0]['start_relative_s'])+clocks['parser_origin_s']-clocks['capture_started_s']
            end=float(omissions[-1]['start_relative_s'])+clocks['parser_origin_s']-clocks['capture_started_s']
            decode_notes += ['', f'`{r["clip"]}` 的 {missing} 个编码包（tag {omissions[0]["tag_before"]}–{omissions[-1]["tag_before"]}）已存在原始码流和 MP4，离线/实时解码均无对应输出；不是 header-only 包。',
                f'对应 PC 解析时间约为录制开始后 {start:.6f}–{end:.6f} s；解码 PTS 的最大空缺区间为 {fmt(largest["start_relative_s"])}–{fmt(largest["end_relative_s"])} s（{fmt(largest["interval_ms"])} ms）。',
                '实时侧车缺失与离线缺失是同一批 tag，不能重复计为 40 帧。FFmpeg 记录宏块解码错误；没有证据仅凭这些文件区分无线丢包、发送码流问题或解码器兼容性。','']
    lines += decode_notes
    lines += ['', '## OAFD 内参的参考价值','',
        f'来源：[geturin/OAFD_Monocular 固定提交的 tello.yaml]({reference["source_url"]})，提交 `{reference["source_commit"]}`，原文件 SHA256 `{reference["source_sha256"]}`。副本与 MIT LICENSE 保存在 references/。',
        '来源与本批数据同为 960×720，因此无需分辨率缩放；它没有证明是本机、同固件/防抖/裁剪条件，也未在检查的仓库中提供本机棋盘格观察或内参重投影误差。src/depthmap_calibration.py 是深度尺度拟合，不是相机内参标定。','',
        '| 参数 | 借用值 | 单位 |','|---|---:|---|']
    lines += [f'| {k} | {v} | '+('像素' if k in ('fx','fy','cx','cy') else '无量纲')+' |' for k,v in reference['intrinsics'].items()]
    lines += ['', '已生成 configs/c/tello_oafd_960x720_provisional.yaml，并通过电脑 OpenCV FileStorage 读取与数值一致性检查。',
        '转换旧版 Camera.fx 等为 v1.0 的 Camera1.fx 等，加入 File.version=1.0；帧率20→30，仅表示本批数据标称帧率；没有改变实际侧车时间。保持1000特征/8层/1.2/FAST20与7，初始化提取器为5000。',
        '保留来源畸变系数作为临时候选（取代此前 FoV+零畸变候选），未搬用外来 IMU/Tbc，也不添加未提供的 k3；无 newWidth/newHeight。',
        '**临时内参，待标定后重跑。** 本阶段未完成本机标定，没有可报告的本机重投影误差。正式棋盘格标定时可以把此 K 作为初值，使用本机观测重新优化 K 与畸变，不能锁定这些借用值来声称标定完成。',
        '[DJI TT 官方规格](https://www.dji.com/support/product/robomaster-tt)给出82.6°视场角，但该页未注明水平/对角线；不能可靠地由这个数确定960×720的焦距。当前优先使用有明确像素参数的 OAFD 候选。','',
        '## 下一步建议与待确认项','',
        '1. 工作分辨率建议960×720原图，使用这份 provisional 配置；不在 C0 开始跟踪实测。',
        '2. 建议按离线解码帧关联到原始 packet tag，使用 PC t_parser_emit 相对时间；保留真实间隔，转整数纳秒后输入运行适配器。明确它是电脑解析可用时间，而不是相机采集时间。不要按帧序号重新铺成30fps。',
        '3. 预录帧仅用于建立解码参考，正式测评从 capture.started 之后的可解码帧开始；保留坏帧标记和缺帧间隔，不静默修复、二次编码或删掉失败片段。',
        '4. 确认后进入 C1/C2 初步版：每段3次、CPU/DMC固定performance并恢复、A76绑核；稳定片段再做焦距±10%各3次。无真值不报告ATE。正式标定后再按每段5次重跑；B2等正式标定。',
        '5. 后续标定脚本输入棋盘格视频、内角点数与方格尺寸，输出本机重投影误差/K/畸变/ORB YAML；当前无棋盘格视频，尚未执行。取消H.264退化MH01方案。','',
        '## 复现与文件','',
        '在主项目根目录执行：','',
        '```powershell',
        'powershell -ExecutionPolicy Bypass -File rk3588/orbslam3_cpu_baseline/scripts/inventory_c0.ps1',
        '. scripts/project_env.ps1',
        '& $ProjectPython rk3588/orbslam3_cpu_baseline/scripts/prepare_tello_reference.py',
        '& $ProjectPython rk3588/orbslam3_cpu_baseline/scripts/report_c0.py',
        '```','',
        '- inventory.csv：全部计数、码率、时间轴帧率、预录与解码质量。',
        '- timestamp_stats.csv / timing_events.csv：分时钟分布与所有异常位置。',
        '- source_manifest.* / acceptance.json：原始只读、SHA和验收；raw/保留ffprobe原始JSON、日志、逐帧映射。',
        '- references/ / reference_intrinsics.json：固定上游源文件、许可、候选参数与转换审计。',
        '- 3项独立小测试验证NAL封装差别不改变切片哈希、损坏长度拒绝、PC时间突增不被压平。',
        '- 本阶段未运行C2，初始化/跟踪/地图/内点/耗时/轨迹一致性均为“未完成”。']
    (out/'C0_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('C0_REPORT_GENERATED '+str(out/'C0_REPORT.md'))

if __name__=='__main__':
    main()
