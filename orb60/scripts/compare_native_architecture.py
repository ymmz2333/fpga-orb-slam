"""Compare accepted native frame runs under identical modeled DDR service."""
import argparse
import json
from pathlib import Path


def key(run):
    return (run.get('ddr_capacity_bytes_per_second',run['ddr_beats_per_cycle']*800000000),run['random_stall_percent'],run['seed'],
            tuple(run.get('read_initial_delay_ns',[n*10 for n in run['read_initial_delay_cycles']])),
            run.get('hp_capacity_bytes_per_second',800000000),
            tuple(run.get('hp_mapping',[0,3,1,2,0,1,3,2])),
            tuple(run.get('write_response_delay_ns',[20,310])))


def rtl(root):
    return {(x['kernel'],x['name']):x['sha256'] for x in json.loads((root/'rtl_manifest.json').read_text())}


def patch_ports(frame):
    result={}
    for index,name in ((4,'raw'),(5,'blur')):
        port=frame['axi_ports'][index];assert port['port']==index
        # V1 counted only pending-without-RVALID. It is not a denominator for
        # outstanding over all pending cycles. Preserve that raw evidence;
        # leave this derived mean unavailable rather than invent a correction.
        pending=port['read_pending_cycles'] if 'read_wait_for_data_cycles' in port else None
        total=port.get('read_outstanding_cycle_sum',0)
        result[name]=dict(maximum=port['read_outstanding_max'],
            whole_frame_mean=total/frame['cycles'],
            mean_when_read_pending=total/pending if pending else (0 if pending==0 else None),
            accepted_ar=port.get('accepted_ar'),accepted_r=port.get('accepted_r'),
            pending_cycles=pending)
    return result


def compare(candidate,baseline,output):
    for root in (candidate,baseline):
        state=json.loads((root/'status.json').read_text(encoding='utf-8-sig'))
        assert state['State']=='SUCCEEDED' and state['Stage']=='COMPLETE'
    new=json.loads((candidate/'performance.json').read_text())
    old=json.loads((baseline/'performance.json').read_text())
    assert new['status']==old['status']=='PASS'
    for record in (new,old):
        period=record['runs'][0]['clock_period_ps']
        assert 5000<=period<=10000 and abs(record['frequency_mhz']-1000000/period)<1e-9
        assert all(run['clock_period_ps']==period for run in record['runs'])
    assert new['rtl_unchanged'] and old['rtl_unchanged']
    assert len({key(r) for r in new['runs']})==len(new['runs'])
    assert len({key(r) for r in old['runs']})==len(old['runs'])
    reference={key(run):run for run in old['runs']}
    matched_profiles=set(reference)&{key(r) for r in new['runs']}
    assert matched_profiles,'No identical modeled DDR service configuration'
    new_rtl,old_rtl=rtl(candidate),rtl(baseline)
    kernels={kernel for kernel,_ in new_rtl}|{kernel for kernel,_ in old_rtl}
    same_rtl={kernel:{k:v for k,v in new_rtl.items() if k[0]==kernel}=={k:v for k,v in old_rtl.items() if k[0]==kernel}
              for kernel in kernels}
    matched_frames=0
    rows=[]
    for run in new['runs']:
        prior=reference.get(key(run))
        previous_frames={f['frame']:f for f in prior['frames']} if prior else {}
        assert len(run['frames'])==3 and len({f['frame'] for f in run['frames']})==3
        if prior:assert set(previous_frames)=={f['frame'] for f in run['frames']}
        for frame in run['frames']:
            row=dict(ddr_beats_per_cycle=run['ddr_beats_per_cycle'],stall_percent=run['random_stall_percent'],
                     read_delay=run['read_initial_delay_cycles'],frame=frame['frame'],points=frame['selected'],
                     milliseconds=frame['milliseconds'],equivalent_fps=frame['equivalent_fps'],
                     axi_bytes=frame['read_bytes']+frame['write_bytes'],
                     service_utilization=frame['ddr_service'].get('capacity_utilization',
                         frame['ddr_service'].get('service_slot_utilization')),
                     service_utilization_basis=('bytes_per_second_capacity' if
                         'capacity_utilization' in frame['ddr_service'] else 'legacy_beat_slots'),
                     patch_read_outstanding=patch_ports(frame))
            if prior:
                ref=previous_frames[frame['frame']];matched_frames+=1
                assert ref['selected']==frame['selected']
                assert ref['read_bytes']==frame['read_bytes'] and ref['write_bytes']==frame['write_bytes']
                previous=ref['milliseconds']
                row.update(previous_ms=previous,
                           latency_reduction_percent=100*(previous-frame['milliseconds'])/previous)
            # Adjacent stage durations include DDR and waiting. This diagnostic
            # scheduling bound is not another measured implementation/FPS.
            layers=frame['layers']
            dominant=[l for l in range(7) if layers[l]['descriptor_cycles']>layers[l+1]['image_cycles']]
            half_scan=layers[0]['image_cycles']/2+sum(max(layers[l]['descriptor_cycles'],
                       layers[l+1]['image_cycles']/2 if l<7 else 0) for l in range(8))
            row.update(descriptor_dominates_next_image_levels=dominant,
                       ideal_half_scan_schedule_ms=half_scan/(new['frequency_mhz']*1000),
                       layers=layers,axi_ports=frame['axi_ports'])
            rows.append(row)
    assert matched_frames==len(matched_profiles)*3
    output.mkdir(parents=True,exist_ok=False)
    result=dict(scope='Exact native RTL tests and modeled DDR only; no routed or physical-board claim',
                candidate=str(candidate.resolve()),baseline=str(baseline.resolve()),frequency_mhz=new['frequency_mhz'],baseline_frequency_mhz=old['frequency_mhz'],
                frames=rows,matched_baseline_frames=matched_frames,identical_rtl_by_kernel=same_rtl,
                notes=['Busy/wait counters overlap; do not sum them as exclusive frame stalls',
                  'FIFO blocked pins can be prequalified by HLS; zero blocked-pin observations do not prove absence of backpressure',
                  'Only matching DDR profiles have latency deltas; missing reference configurations remain explicit',
                  'When layer and descriptor RTL both change, latency delta is the combined implementation gain',
                  'Ideal half-scan timing ignores changed DDR demand and host scheduling; it is a diagnostic bound'])
    (output/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# 候选整帧 RTL 对照','',
           f"{new['frequency_mhz']:g} MHz 候选／{old['frequency_mhz']:g} MHz 参照、实际各频率 RTL、相同 DDR 字节/s 与首读 ns；{len(rows)} 帧 golden 输出精确通过，{matched_frames} 帧有匹配参照。数值不代表实体板 FPS。",'',
           'DDR表中beat和延迟拍数以100MHz（10ns）为参照；按各自新时钟边沿量化，误差不足一个新时钟周期。随机停顿是相同参数和种子，不保证跨频率事件序列完全相同。','',
           '| DDR beat/10ns | 随机停顿 | 首读资格延迟/10ns | 点数 | 新耗时/ms | 等效 FPS | 旧耗时/ms | 延迟减少 |',
           '|---:|---:|---|---:|---:|---:|---:|---:|']
    for r in rows:
        previous=f"{r['previous_ms']:.5f}" if 'previous_ms' in r else '无对应基线'
        delta=f"{r['latency_reduction_percent']:.3f}%" if 'previous_ms' in r else '—'
        lines.append(f"| {r['ddr_beats_per_cycle']} | {r['stall_percent']}% | {r['read_delay']} | {r['points']} | {r['milliseconds']:.5f} | {r['equivalent_fps']:.2f} | {previous} | {delta} |")
    pressure=[r for r in rows if r['points']==942]
    lines+=['',f"942点压力帧最大耗时 {max(r['milliseconds'] for r in pressure):.5f} ms。",
            f"与参照相同的 RTL：{same_rtl}；两核均改变时，延迟差值表示组合收益。",'',
            '| 首读资格延迟/拍 | DDR beat/拍 | RAW最大/有请求时平均outstanding | BLUR最大/有请求时平均outstanding |',
            '|---|---:|---|---|']
    for r in pressure:
        a,b=(r['patch_read_outstanding'][k] for k in ('raw','blur'))
        def pending_mean(port):
            value=port['mean_when_read_pending']
            return f'{value:.3f}' if value is not None else '旧统计口径不可用'
        lines.append(f"| {r['read_delay']} | {r['ddr_beats_per_cycle']} | {a['maximum']} / {pending_mean(a)} | {b['maximum']} / {pending_mean(b)} |")
    lines+=['','outstanding是实际接受AR至RLAST期间的计数；有请求时平均值与整帧平均值分开记录。',
            '阶段busy包含等待，各端口等待可重叠；不得相加当作整帧独占停顿。',
            '资源、时序和板上性能需要各自证据；本文件只给出实际RTL在这些DDR配置下的仿真结果。']
    (output/'SUMMARY_ZH.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'NATIVE_ARCHITECTURE_COMPARISON_PASS frames={len(rows)} matched_baseline_frames={matched_frames}')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('candidate','baseline','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();compare(args.candidate,args.baseline,args.output)
