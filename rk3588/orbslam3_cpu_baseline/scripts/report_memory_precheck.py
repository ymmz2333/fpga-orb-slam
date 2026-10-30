"""Read-only reconstruction of P1 errors/frequencies and a Chinese failure report."""
import argparse,collections,csv,hashlib,json,pathlib,re
ROOT=pathlib.Path(__file__).resolve().parent.parent

def read(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

def write(path,rows):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);a=p.parse_args()
    root=ROOT/'reports/b3_precheck'/a.batch;raw=root/'raw'
    for row in read(raw/'board_manifest.csv'):
        path=raw/row['path']
        if path.stat().st_size!=int(row['bytes']) or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Transport SHA256 mismatch '+row['path'])
    state=json.loads((raw/'state.json').read_text());summaries=[];errors=[]
    directories=sorted(path for path in raw.iterdir() if path.is_dir())
    if len(directories)!=len(state['conditions']):raise ValueError('Condition directory mismatch')
    for item,directory in zip(state['conditions'],directories):
        text=(directory/'memtester.log').read_text(errors='replace');samples=read(directory/'telemetry.csv')
        failures=list(re.finditer(r'FAILURE:[^\n\r]+',text))
        reported=[int(n) for n in re.findall(r'had found (\d+) failures',text)]
        if sum(reported)!=len(failures):raise ValueError('Failure count/summary mismatch')
        for n,match in enumerate(failures,1):
            detail=match.group();following=text[match.end():match.end()+600]
            physical=re.search(r'physical address:?\s+(0x[\da-f]+)(?:,\s*(0x[\da-f]+))?',following,re.I)
            offset=re.search(r'at offset (0x[\da-f]+)',detail,re.I)
            xor=re.search(r'readA\^readB:(0x[\da-f]+)',detail,re.I)
            address=physical[1].lower() if physical else ''
            errors.append(dict(condition=item['condition'],directory=directory.name,error_index=n,
                cycle=text[:match.start()].count('memtester version'),offset=offset[1] if offset else '',
                physical_a=address,physical_b=physical[2].lower() if physical and physical[2] else '',
                physical_a_page=hex(int(address,16)&~4095) if address else '',xor=xor[1] if xor else '',
                detail=detail[:350],following_detail=following.splitlines()[1][:350] if following.startswith('\n') else following.splitlines()[0][:350]))
        frequencies=sorted({int(r['dmc_cur_freq']) for r in samples})
        temperatures=[int(v)/1000 for r in samples for k,v in r.items() if k.endswith('_temp_mc')]
        cpu={policy:sorted({int(r[policy+'_scaling_cur_freq']) for r in samples}) for policy in ('policy4','policy6')}
        max_temp=max(temperatures)
        if abs(max_temp-item['max_temperature_c'])>1e-10:raise ValueError('Telemetry temperature mismatch')
        summaries.append(dict(condition=item['condition'],requested_dmc_hz=item['requested_dmc_hz'],
            elapsed_s=item['elapsed_s'],elapsed_minutes=item['elapsed_s']/60,cycles=item['cycles_complete'],
            requested_memory_mib=item['requested_memory_mib'],memory_verified=item['requested_memory_verified'],
            failure_records=len(failures),cycle_failure_counts='/'.join(map(str,reported)),exit_code=item['exit_code'],
            status=item['status'],dmc_observed_hz='/'.join(map(str,frequencies)),
            a76_policy4_khz='/'.join(map(str,cpu['policy4'])),a76_policy6_khz='/'.join(map(str,cpu['policy6'])),
            affinity_verified=bool(item['observed_worker_masks']==[[4,5,6,7]] and not item['affinity_violations']),
            max_temperature_c=max_temp,cpu_drop=item['cpu_drop'],dmc_drop=item['dmc_drop']))
    write(root/'memory_summary.csv',summaries)
    if errors:write(root/'memory_errors.csv',errors)
    hashes=read(raw/'png_hashes.csv');mismatches=sum(r['match']!='True' for r in hashes)
    if len(hashes)!=state['hash_checks']['checks'] or mismatches!=state['hash_checks']['mismatches']:raise ValueError('PNG hash summary mismatch')
    pages=collections.Counter(r['physical_a_page'] for r in errors)
    kernel_matches=[]
    for name in ('dmesg.log','kernel_journal.log'):
        for line in (raw/name).read_text(errors='replace').splitlines():
            if re.search(r'out of memory|oom-kill|killed process|segfault|hardware error|EDAC.*error|undervolt',line,re.I):kernel_matches.append(dict(file=name,line=line[:500]))
    result=dict(status=state['status'],errors=len(errors),reported_first_side_pages=dict(pages),
        png_checks=len(hashes),png_mismatches=mismatches,settings_restored=state['settings_restored'],
        kernel_fault_matches=kernel_matches,b3_started=state['b3_started'],
        elapsed_target_s=state['duration_per_condition_s'],all_conditions_zero_error=False,
        limitations=['Runs stopped after failed complete cycles; none qualified for >=2 hours zero errors',
            'Physical addresses are reported by rktoolkit, not independently mapped to DRAM chips',
            'Error totals have different exposure durations/cycles, not an error-rate comparison'])
    (root/'verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# P1 内存稳定性失败报告','',
        '**P1未通过，三个条件均有明确内存数据不一致。P2/P3实机验证暂停，B3未启动。**','',
        '这是测试程序自身输出FAILURE且退出非零，不是监督器解析文字误报。所有原始日志、遥测、失败记录保留；11个板上文件SHA256传输校验通过。','',
        '## 结果','',
        '| DMC条件 | 内存（MiB） | 实际时长（分钟） | 完整循环 | 失败记录 | 退出码 |',
        '|---|---:|---:|---:|---:|---:|']
    names={'performance':'固定1560MHz（performance）','dmc_ondemand':'dmc_ondemand','fixed':'固定1068MHz'}
    for r in summaries:lines.append('| %s | %d | %.2f | %d | %d | %d |'%(names[r['condition']],r['requested_memory_mib'],r['elapsed_minutes'],r['cycles'],r['failure_records'],r['exit_code']))
    lines+=['','每档目标至少7200秒，但已报错的完整循环结束后提前停止。故这些时长不是两小时通过测试；不能因为没有跑满两小时而忽略已发现错误，也没有用通过的一轮替换失败。',
        '1068MHz第一循环报告0 failures，第二循环报告6 failures后退出。短测和一个完整循环通过仍不足以证明稳定。三个条件时间/循环不同，45/84/6只是日志失败记录数量，不能据此比较可靠性或误码率。','',
        'CPU4–7实际亲和性逐次核验，A76 policy4/6全程2256000kHz；所有条件swap=0，按MemAvailable的70%申请并mlock，实际申请大小核验通过。固定档DMC全程分别1560000000和1068000000Hz；动态档观察到528/1068/1560MHz。没有CPU/DMC降频标志，所有传感器最高43.461°C；没有DDR专属温度/实际输入电压测量，不能据此排除所有热或供电因素。','',
        '## 错误证据','',
        '```text','1560MHz:',
        'FAILURE: possible bad address line at offset 0x3a3f8950.',
        'FAILURE: 0xe7a72f2d != 0xe7a62f2c (readA^readB:0x00010001) at offset 0x3a3f7054.',
        '1068MHz:',
        'FAILURE: 0xf98a7374 != 0xf98b7375 (readA^readB:0x00010001) at offset 0x38541194.',
        'physical address: 0x18cd5e194, 0x8e3db1a4, reread:0xf98a7374, 0xf98b7375',
        '```','',
        '工具报告的第一侧物理页分布：']
    for page,count in sorted(pages.items()):lines.append('- `%s`：%d条。'%(page,count))
    lines+=['','135条记录中134条集中在0x18cd5e000和0x18cd5f000两页，另一条为0x1ff5d7000。不同分配虚拟偏移变化，而工具报告集中到相同物理页；此前stressapptest的6条错误同样报告这两页附近。这是局部数据完整性问题的强线索，尚不能直接确诊某个DRAM芯片损坏。地址来自rktoolkit报告，具体芯片映射和异常写入来源未验证。重新读取多数仍为同一错误值，完整逐条证据见memory_errors.csv。','',
        '## 判定与历史结果影响','',
        '- 1068MHz也失败，不能采用它作为已验证稳定的B3条件。最高频率是否加重问题不能凭三段不同曝光时长的错误总数确定。',
        '- GCC9.4此前两次Segmentation fault/ICE无OOM证据，后续重编通过；与当前平台问题相容，但不能证明崩溃由同一故障造成。缺失g2o依赖仍是独立问题。',
        '- 本轮内核日志未发现OOM/segfault/EDAC错误/欠压匹配；没有内核报告不抵消用户态的确定数据不一致。',
        '- 两段Tello冷缓存三轮共11871次SHA256比较均相同，说明这些读盘检查未发现输入文件改变，不能覆盖解码后图像、特征数组或SLAM内存。',
        '- 已有A2/A3/B1/C2/B2 raw和数值保留，但平台恢复稳定之前，实验结论仍需保留数据完整性疑点；尚不能说某一次SLAM结果必定被翻转，也不能直接用于硬件方案定型。','',
        '## 已恢复与下一步','',
        '正式监督任务FAILED、exit_code=2。原CPU governor interactive、DMC governor dmc_ondemand、min528MHz/max1560MHz均恢复；实机再次核对通过，swap=0，没有遗留memtester/stressapptest/mono_euroc。原始运行开始2026-10-05 14:33:25、结束16:24:00（日本时间）。',
        '电源铭牌HT-PD27W-CN，27W；支持5.1V/5A、9V/3A、12V/2.25A、15V/1.8A。实际协商电压不可读。',
        '按用户门禁要求在这里停止，不启动新的压力测试、重编、P2/P3或B3。建议下一步先以已知可靠且符合板卡要求的电源和线材作对照、冷启动后重复同样门禁，并将两页集中出错的原始证据交给板卡厂商排查DDR/固件。更低528MHz或不同系统镜像的对照属于后续决策；不要通过屏蔽坏页、忽略错误或挑选通过运行来放行。','',
        '## 重现','',
        '```powershell','. ..\\..\\scripts\\project_env.ps1','& $ProjectPython scripts/report_memory_precheck.py --batch P1_full_20261005','```','',
        '脚本从raw重新计算失败数、频率/温度和物理页分布，校验板上SHA256；所有派生CSV/JSON位于raw外，原始文件不改。']
    (root/'P1_FAILURE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('P1_REPORT_VERIFIED conditions=%d errors=%d png_checks=%d mismatches=%d B3_NOT_STARTED'%(len(summaries),len(errors),len(hashes),mismatches))
if __name__=='__main__':main()
