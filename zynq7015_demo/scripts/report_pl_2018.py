"""Summarize completed Vivado synthesis separately from timing acceptance."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys


def inspect(root):
    root = root.resolve()
    output = root / 'vivado'
    status = json.loads((root / 'status.json').read_text())
    timing = (output / 'post_synth_timing.rpt').read_text(errors='replace')
    utilization = (output / 'post_synth_utilization.rpt').read_text(errors='replace')
    drc = (output / 'post_synth_drc.rpt').read_text(errors='replace')
    clock = (output / 'post_synth_clocks.rpt').read_text(errors='replace')
    check_timing = (output / 'post_synth_check_timing.rpt').read_text(errors='replace')
    ip = (output / 'ip_status.rpt').read_text(errors='replace')
    number = r'(-?\d+\.\d+)'
    row = re.search(r'^\s*' + r'\s+'.join([number, number, r'(\d+)', r'(\d+)', number,
                         number, r'(\d+)', r'(\d+)', number, number, r'(\d+)', r'(\d+)']) + r'\s*$', timing, re.M)
    if not row:
        raise ValueError('Timing summary row not found')
    values = row.groups()
    metrics = dict(wns_ns=float(values[0]), tns_ns=float(values[1]), setup_failing_endpoints=int(values[2]),
                   whs_ns=float(values[4]), ths_ns=float(values[5]), hold_failing_endpoints=int(values[6]),
                   wpws_ns=float(values[8]), tpws_ns=float(values[9]), pulse_failing_endpoints=int(values[10]))
    metrics['timing_status'] = 'PASS' if metrics['wns_ns'] >= 0 and metrics['whs_ns'] >= 0 and metrics['wpws_ns'] >= 0 else 'FAIL'
    resources = {}
    for label, key in [('Slice LUTs*','lut'), ('Slice Registers','registers'), ('Block RAM Tile','bram_tiles'), ('DSPs','dsp')]:
        entries = [line.split('|') for line in utilization.splitlines() if line.startswith('|')]
        entry = next(e for e in entries if e[1].strip() == label)
        resources[key] = dict(used=float(entry[2]), available=float(entry[4]), percent=float(entry[5]))
    rules = []
    for rule, severity, count in re.findall(r'^\|\s*([A-Z]+-\d+)\s*\|\s*(Warning|Critical Warning|Error)\s*\|[^|]*\|\s*(\d+)\s*\|', drc, re.M):
        rules.append(dict(rule=rule, severity=severity, count=int(count)))
    timing_coverage_nonzero = re.findall(r'There are ([1-9]\d*) ([^\n]+)', check_timing)
    report_files = ['post_synth_utilization.rpt','post_synth_timing.rpt','post_synth_drc.rpt',
                    'post_synth_clocks.rpt','post_synth_check_timing.rpt','ip_status.rpt','s_wrapper_synth.dcp']
    result = dict(synthesis_flow_status=status['status'], **metrics, resources=resources,
                  stage='post_synthesis_estimate', part=status['part'], top=status['top'],
                  mem2_slices=status.get('mem2_slices',False),
                  video2=status.get('video2',False),scope=status.get('scope'),
                  clock_target_mhz=150,
                  clock_150_mhz_reported=bool(re.search(r'^clk_out1_s_clockgen_0\s+6\.667\s+', clock, re.M)),
                  ip_up_to_date=len(re.findall(r'^\|\s*s_\S+\s*\|\s*Up-to-date',ip,re.M)),
                  coverage_nonzero=timing_coverage_nonzero,
                  drc=rules, drc_rule_limits_reached=any(r['rule']=='CHECK-3' for r in rules),
                  implementation_run=False, hardware_acceptance='NOT_VERIFIED',
                  checkpoint_sha256=hashlib.sha256((output/'s_wrapper_synth.dcp').read_bytes()).hexdigest(),
                  report_sha256={f:hashlib.sha256((output/f).read_bytes()).hexdigest() for f in report_files[:-1]})
    inspections = sorted(root.glob('inspection_*/methodology.rpt'))
    if inspections:
        methodology = inspections[-1].read_text(errors='replace')
        result['methodology_report'] = str(inspections[-1])
        result['methodology_rules'] = [dict(rule=rule,severity=severity,count=int(count))
            for rule,severity,count in re.findall(r'^\|\s*([A-Z]+-\d+)\s*\|\s*(Warning|Critical Warning|Error)\s*\|[^|]*\|\s*(\d+)\s*\|',methodology,re.M)]
    (root/'review.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    text = f'''# Vivado 2018.3 综合检查

- 器件／顶层：`{status['part']}`／`{status['top']}`。
- 综合流程：{status['status']}；时序估计：{metrics['timing_status']}。流程完成与频率验收分别判定。
- 时钟：PS FCLK 100 MHz，ORB 150 MHz（6.667 ns），本报告为综合后估计。
- Setup：WNS {metrics['wns_ns']:.3f} ns，TNS {metrics['tns_ns']:.3f} ns，违例端点 {metrics['setup_failing_endpoints']}。
- Hold：WHS {metrics['whs_ns']:.3f} ns，THS {metrics['ths_ns']:.3f} ns；脉宽 WPWS {metrics['wpws_ns']:.3f} ns。
- `check_timing` 非零问题项：{len(timing_coverage_nonzero)}；IP Up-to-date：{result['ip_up_to_date']}。
- mem2 两个输入端的寄存器切片：{'启用' if result['mem2_slices'] else '未启用'}。

| 资源 | 使用 | 总量 | 占比 |
| --- | ---: | ---: | ---: |
'''
    for key, resource in resources.items():
        text += f"| {key} | {resource['used']:g} | {resource['available']:g} | {resource['percent']:.2f}% |\n"
    text += '\nDRC 报告摘要：\n\n| 规则 | 级别 | 报告数量 |\n| --- | --- | ---: |\n'
    for rule in rules:
        text += f"| {rule['rule']} | {rule['severity']} | {rule['count']} |\n"
    if inspections:
        text += '\n补充方法学检查：' + '；'.join(f"{r['rule']} {r['count']} 项 {r['severity']}" for r in result['methodology_rules']) + '。未创建 waiver。\n'
    text += '''
REQP 报告达到每规则显示上限时，以上是报告数量，不是完整违例总数。DSP 流水线及 RAM 异步控制警告保留，未创建 waiver；需结合总线背压、复位与后续实现验证。

本报告只覆盖本次综合；综合估计不能代替布线后时序、外设板测或持续 30 FPS。SLAM/UI 是 PS 软件。硬件范围以本目录 status.json 的 scope/video2 字段为准；video2 设计包含 HDMI_2 扫描通路，摄像头保留接口。

命令：通过进程隔离 `xilinx-2018.3.cmd` 运行 `synth_only.tcl`，一个综合作业、一个线程。原交接包和既有 bit/ELF 未改写。原始报告、网表和 SHA-256 记录保存在同一运行目录。
'''
    (root/'REVIEW_ZH.md').write_text(text,encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('synthesis_flow_status','timing_status','wns_ns','tns_ns','setup_failing_endpoints','resources')},ensure_ascii=False))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    inspect(parser.parse_args().run)
