"""Review routed timing, resource fit, routing completeness, and DRC independently."""
from pathlib import Path
import argparse
import hashlib
import json
import re


def inspect(root):
    root = root.resolve()
    state = json.loads((root/'status.json').read_text())
    names = ['post_route_timing.rpt','post_route_utilization.rpt','post_route_route_status.rpt',
             'post_route_check_timing.rpt','post_route_clocks.rpt','post_route_drc.rpt','post_route_methodology.rpt']
    for extra in ['post_route_bus_skew.rpt','post_route_cdc.rpt']:
        if (root/extra).is_file():names.append(extra)
    reports = {name:(root/name).read_text(errors='replace') for name in names}
    number=r'(-?\d+\.\d+)'
    pattern=r'^\s*'+r'\s+'.join([number,number,r'(\d+)',r'(\d+)',number,number,
                                r'(\d+)',r'(\d+)',number,number,r'(\d+)',r'(\d+)'])+r'\s*$'
    row=re.search(pattern,reports[names[0]],re.M)
    if not row:
        raise ValueError('Missing routed timing metrics')
    v=row.groups()
    timing=dict(wns_ns=float(v[0]),tns_ns=float(v[1]),setup_failing_endpoints=int(v[2]),
                whs_ns=float(v[4]),ths_ns=float(v[5]),hold_failing_endpoints=int(v[6]),
                wpws_ns=float(v[8]),tpws_ns=float(v[9]),pulse_failing_endpoints=int(v[10]))
    route={}
    for label,key in [('routable nets','routable'),('fully routed nets','fully_routed'),('nets with routing errors','errors')]:
        match=re.search(r'# of '+re.escape(label)+r'[. \t]*:[ \t]*(\d+)',reports[names[2]])
        if not match:
            raise ValueError('Missing routing metric: '+label)
        route[key]=int(match.group(1))
    resources={}
    entries=[line.split('|') for line in reports[names[1]].splitlines() if line.startswith('|')]
    for label,key in [('Slice LUTs','lut'),('Slice Registers','registers'),('Slice','slices'),('Block RAM Tile','bram_tiles'),('DSPs','dsp')]:
        entry=next((e for e in entries if e[1].strip().rstrip('*')==label),None)
        if entry is None:
            raise ValueError('Missing utilization: '+label)
        resources[key]=dict(used=float(entry[2]),available=float(entry[4]),percent=float(entry[5]))
    def rules(text):
        return [dict(rule=rule,severity=severity,count=int(count)) for rule,severity,count in
                re.findall(r'^\|\s*([A-Z][A-Z0-9]*-\d+)\s*\|\s*(Warning|Critical Warning|Error|Advisory)\s*\|[^|]*\|\s*(\d+)\s*\|',text,re.M)]
    drc=rules(reports[names[5]])
    methodology=rules(reports[names[6]])
    coverage=re.findall(r'There are ([1-9]\d*) ([^\n]+)',reports[names[3]])
    serialized_ports=[];coverage_reviewed=not coverage
    if state.get('video2'):
        section=re.search(r'^6\. checking no_output_delay\s*\n-+\n([\s\S]*?)(?=^7\.)',reports[names[3]],re.M)
        if section:
            serialized_ports=re.findall(r'^hdmi_(?:clk_p|dat_p\[[012]\])$',section.group(1),re.M)
        expected={'hdmi_clk_p','hdmi_dat_p[0]','hdmi_dat_p[1]','hdmi_dat_p[2]'}
        coverage_reviewed=(set(serialized_ports)==expected and len(coverage)==1 and
                           coverage[0][0]=='4' and coverage[0][1].startswith('ports with no output delay specified'))
    # Ensure a truncated/empty check_timing report cannot be mistaken for zero.
    for category in ['no_clock','unconstrained_internal_endpoints','no_input_delay','no_output_delay','loops']:
        if not re.search(r'^\d+\. checking '+category+r'\s*\n-+\n\s*There are \d+',reports[names[3]],re.M):
            raise ValueError('Missing timing coverage category: '+category)
    critical=[r for r in drc+methodology if r['severity'] in ('Error','Critical Warning')]
    clocks=reports[names[4]]
    clock_ok=bool(re.search(r'^clk_out1_s_clockgen_0\s+6\.667\s+',clocks,re.M))
    conditions=dict(flow_complete=state['status']=='FLOW_COMPLETE',
                    timing_nonnegative=all(timing[k]>=0 for k in ('wns_ns','whs_ns','wpws_ns')),
                    no_failing_endpoints=all(timing[k]==0 for k in ('setup_failing_endpoints','hold_failing_endpoints','pulse_failing_endpoints')),
                    all_nets_routed=route['routable']==route['fully_routed'] and route['errors']==0,
                    coverage_zero=not coverage, no_critical_drc_methodology=not critical,
                    resource_fit=all(r['used']<=r['available'] for r in resources.values()),clock_150mhz=clock_ok)
    if state.get('video2'):
        del conditions['coverage_zero']
        conditions['internal_coverage_complete_external_TMDS_boundary_listed']=coverage_reviewed
        conditions['video_clocks_74_25_and_371_25']=bool(re.search(r'^clk_out1_s_video_clock_0\s+2\.694\s+',clocks,re.M) and re.search(r'^clk_out2_s_video_clock_0\s+13\.468\s+',clocks,re.M))
        skew=reports.get('post_route_bus_skew.rpt','')
        skew_slacks=[float(v) for v in re.findall(r'Slack \((?:MET|VIOLATED)\)\s*:\s*(-?\d+\.\d+)ns',skew)]
        conditions['fifo_gray_bus_skew_met']=len(skew_slacks)>=2 and min(skew_slacks)>=0
        cdc=reports.get('post_route_cdc.rpt','')
        conditions['cdc_report_without_warning_critical']=bool(cdc) and not re.search(r'^CDC-\d+\s+(?:Warning|Critical)',cdc,re.M)
    result=dict(status='PASS' if all(conditions.values()) else 'FAIL',stage='post_route',
                part=state['part'],top=state['top'],strategy=state['strategy'],checks=conditions,
                timing=timing,routing=route,resources=resources,drc=drc,methodology=methodology,
                coverage_nonzero=coverage,critical_violations=critical,
                video2=state.get('video2',False),serialized_external_ports=serialized_ports,
                timing_scope='Internal clocks/datapaths; serialized TMDS pins have no PCB/receiver delay model' if state.get('video2') else 'Clock and path coverage checked',
                drc_rule_limits_reached=any(r['rule']=='CHECK-3' for r in drc),
                bitstream_generated=False,hardware_acceptance='NOT_VERIFIED',
                report_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names},
                checkpoint_sha256=hashlib.sha256((root/'s_wrapper_routed.dcp').read_bytes()).hexdigest())
    (root/'review.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    text=f'''# Vivado 2018.3 布局布线检查

- 目标：`{state['part']}`／`{state['top']}`；策略：`{state['strategy']}`。
- 工具报告验收：{result['status']}；物理板端验收：NOT_VERIFIED。
- 时钟：PS FCLK 100 MHz，ORB 150 MHz（6.667 ns）。
- Setup：WNS {timing['wns_ns']:.3f} ns、TNS {timing['tns_ns']:.3f} ns、违例端点 {timing['setup_failing_endpoints']}。
- Hold：WHS {timing['whs_ns']:.3f} ns、THS {timing['ths_ns']:.3f} ns、违例端点 {timing['hold_failing_endpoints']}。
- Pulse width：WPWS {timing['wpws_ns']:.3f} ns、TPWS {timing['tpws_ns']:.3f} ns。
- 布线：可布线 {route['routable']}，已完全布线 {route['fully_routed']}，布线错误 {route['errors']}。
- 约束覆盖非零问题项：{len(coverage)}；DRC／方法学 Error 或 Critical Warning 项：{len(critical)}。

| 资源 | 使用 | 总量 | 占比 |
| --- | ---: | ---: | ---: |
'''
    for key,r in resources.items():
        text+=f"| {key} | {r['used']:g} | {r['available']:g} | {r['percent']:.2f}% |\n"
    text+='\n| 检查 | 结果 |\n| --- | --- |\n'
    for key,value in conditions.items():
        text+=f"| {key} | {'PASS' if value else 'FAIL'} |\n"
    text+='\nDRC／方法学报告项：\n\n| 来源 | 规则 | 级别 | 报告数量 |\n| --- | --- | --- | ---: |\n'
    for origin,items in [('DRC',drc),('Methodology',methodology)]:
        for r in items:
            text+=f"| {origin} | {r['rule']} | {r['severity']} | {r['count']} |\n"
    text+='''
报告如包含 CHECK-3，表示部分规则达到显示上限，不能把摘要当作全部真实警告数量。没有创建 waiver。常规警告需要与实际复位／背压验证结合评估。

本次从已复核的综合网表继续，未重新生成 HLS、未更换器件、未放宽 150 MHz 约束。通过进程隔离的 xilinx-2018.3.cmd 执行，一个作业／线程。只做到 route_design，没有生成 bitstream，没有访问 JTAG 或烧板。

具体硬件范围见 video2 字段。PS 软件、物理接口、输出一致性和整机持续 30 FPS 须另行验收。
'''
    if state.get('video2'):
        text+='\nHDMI_2 范围：1280×720p60，像素74.25MHz、串行371.25MHz。内部时钟／端点必须覆盖；4个序列化TMDS正端口没有外部PCB／接收器延迟模型，仍在coverage_nonzero和serialized_external_ports中列出，未填造output_delay或创建输出false_path。此PASS仅表示上述内部时序、FIFO Gray总线偏斜、CDC、资源与DRC复核通过，不代表HDMI电气眼图认证；串行器UNISIM及真实显示器功能另外验证。\n'
    (root/'REVIEW_ZH.md').write_text(text,encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','timing','routing','resources','checks')},ensure_ascii=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    inspect(p.parse_args().run)
