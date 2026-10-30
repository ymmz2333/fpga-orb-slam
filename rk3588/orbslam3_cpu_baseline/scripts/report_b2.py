"""Recompute B2 smoke report from immutable raw; preserve unavailable/failed observations."""
import argparse,csv,hashlib,json,math,pathlib,shutil,statistics,tempfile
from analyze_b2 import analyze
from analyze_c import read
from analyze_a2 import describe
ROOT=pathlib.Path(__file__).resolve().parent.parent

def write(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def label(name):
    return 'MH01 752×480' if name=='MH01' else ('Tello 18:49:29' if '184929' in name else 'Tello 20:06:48')

def formatted(value,decimals=2,percent=False):
    if value is None or value=='':return '未完成'
    if isinstance(value,(float,int)):
        if percent:value*=100
        return ('%.*f'%(decimals,value))+('%' if percent else '')
    return str(value)

def table(lines,headers,rows):
    lines.extend(['','| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|'])
    lines.extend('| '+' | '.join(str(v) for v in row)+' |' for row in rows)

def verify_manifest(raw):
    rows=read(raw/'raw_manifest.csv')
    for row in rows:
        path=raw/row['path']
        if path.stat().st_size!=int(row['bytes']) or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Raw SHA256 mismatch '+row['path'])
    return len(rows),sum(int(r['bytes']) for r in rows)

def recompute(root):
    raw=root/'raw';state=json.loads((raw/'batch_state.json').read_text(encoding='utf-8'))
    if state['status']!='FINISHED':raise ValueError('B2 batch is not finished')
    file_count,byte_count=verify_manifest(raw)
    manifest=json.loads((raw/'configs/manifest.json').read_text(encoding='utf-8'))
    lookup={d['name']:dict(d) for d in manifest['datasets']};attempts=[];evidence=[];max_temp=0
    for item in state['schedule']:
        d=lookup[item['dataset']];folder=raw/'runs'/item['folder']
        row=dict(dataset=d['name'],variant=item['variant'],folder=item['folder'],recovery_of=item.get('recovery_of',''),
            process_status=item.get('status','未完成'),acceptance=item.get('acceptance','未完成'),
            intrinsics_label=d['intrinsics_label'],finished_input=False,initialization_frame='',ok_fraction='',
            post_initialization_ok_fraction='',loss_segments='',maps='',normal_points_median='',normal_inliers_median='',
            normal_remaining_median_ms='',normal_remaining_p95_ms='',normal_read_median_ms='',normal_decode_median_ms='',
            cpu_drop='',dmc_drop='',cpu_restored='',dmc_restored='',error=item.get('error',''),
            observed_feature_log_rows='',ate_rmse_m='B3未开始' if d['kind']=='euroc' else '不适用（无真值）')
        meta_path=folder/'run_metadata.json'
        if meta_path.exists():
            meta=json.loads(meta_path.read_text(encoding='utf-8'));row.update(cpu_drop=meta['frequency_drop_detected'],
                dmc_drop=meta['dmc_frequency_drop'],cpu_restored=meta.get('governors_restored'),dmc_restored=meta.get('dmc_restored'),error=meta.get('error') or row['error'])
            telemetry=read(folder/'telemetry.csv')
            max_temp=max(max_temp,max(float(r[k])/1000 for r in telemetry for k in r if k.endswith('_temp_mc')))
            if (folder/'FeatureTimeStats.csv').exists():row['observed_feature_log_rows']=len(read(folder/'FeatureTimeStats.csv'))
            if meta['status']=='FINISHED':
                # Analysis writes only into disposable copies, never raw.
                with tempfile.TemporaryDirectory(prefix='b2-analysis-') as temp:
                    copy=pathlib.Path(temp)
                    for name in ('TrackingStates.csv','TrackingTimeStats.txt','FeatureTimeStats.csv','MapStateStats.csv','Diagnostics_maps.csv','SessionInfo.txt','program.log'):
                        shutil.copy2(folder/name,copy/name)
                    facts=analyze(copy,d,item['variant'],manifest['plan']['smoke_frames'])
                    frames=read(copy/'frames.csv');first=next((n for n,r in enumerate(frames) if int(r['state_after'])==2),None)
                    for key in ('processed_frames','state_ok_frames','state_ok_fraction','first_initialization_frame','loss_segments','maps','inliers_median','remaining_ms_median','points_median'):
                        expected=item['facts'][key];observed=facts[key]
                        if isinstance(expected,(float,int)):
                            if not math.isclose(float(expected),float(observed),rel_tol=1e-12,abs_tol=1e-12):raise ValueError('Board/PC statistic mismatch '+key)
                        elif expected!=observed:raise ValueError('Board/PC statistic mismatch '+key)
                    row.update(finished_input=True,initialization_frame=facts['first_initialization_frame'],ok_fraction=facts['state_ok_fraction'],
                        post_initialization_ok_fraction=sum(int(r['state_after'])==2 for r in frames[first:])/len(frames[first:]) if first is not None else '',
                        loss_segments=facts['loss_segments'],maps=facts['maps'],normal_points_median=facts['points_median'],
                        normal_inliers_median=facts['inliers_median'],normal_remaining_median_ms=facts['remaining_ms_median'],
                        normal_remaining_p95_ms=facts['remaining_ms_p95'],normal_read_median_ms=facts['read_ms_median'],normal_decode_median_ms=facts['decode_ms_median'])
        attempts.append(row)
    selected={}
    for row in attempts:selected[(row['dataset'],row['variant'])]=row
    matrix=[selected[(d['name'],v)] for d in manifest['datasets'] for v in manifest['plan']['variants']]
    write(root/'attempts_verified.csv',attempts);write(root/'matrix_verified.csv',matrix)
    failed=[r for r in attempts if not r['finished_input']]
    complete=[r for r in attempts if r['finished_input']]
    evidence=dict(batch_status=state['status'],attempt_records=len(attempts),successful_complete_attempts=len(complete),
        original_matrix_slots=len(matrix),matrix_successes=sum(r['finished_input'] for r in matrix),
        raw_manifest_files=file_count,raw_manifest_bytes=byte_count,max_all_sensors_c=max_temp,
        cpu_or_dmc_frequency_drop=any(r['cpu_drop'] is True or r['dmc_drop'] is True for r in attempts),
        all_started_attempts_restored=all(r['cpu_restored'] is True and r['dmc_restored'] is True for r in attempts if r['cpu_restored']!=''),
        limitations=['one 600-frame prefix per configuration; no five-run inference','earlier verified page-cache input corruption; original failures retained',
            'MIN Tello 20:06:48 timed out; no thread backtrace retained','no absolute Tello accuracy or metric scale'])
    (root/'acceptance_evidence.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')
    return state,manifest,matrix,attempts,evidence

def regenerate_frontend_summaries(root,state):
    """Derive feature and FAST summaries afresh from retained board records."""
    raw=root/'raw';units=[];thresholds=[]
    for item in state['schedule']:
        check=raw/'candidate_checks'/item['folder']
        if not check.exists():continue
        descriptors=read(check/'descriptor_audit.csv');layers=read(check/'layers.csv')
        unit=dict(dataset=item['dataset'],variant=item['variant'],packet_check=item['packet_check']['status'],
            files=item['packet_check']['files'],audited_descriptors=len(descriptors),
            native_byte_equal=all(r['native_byte_equal']=='1' for r in descriptors) if item['variant']=='V0' else '',
            layer_rows=len(layers),shortfall_total=sum(int(r['shortfall']) for r in layers))
        if unit['packet_check']!='PASS':raise ValueError('Feature check failed '+item['folder'])
        unit.update({'hamming_'+k:v for k,v in describe([int(r['hamming_same_keypoint']) for r in descriptors]).items()})
        units.append(unit)
    for directory in sorted((raw/'fast_probe').iterdir()):
        probe=read(directory/'fast_probe.csv')
        for role in (0,1):
            for threshold in sorted({int(r['threshold']) for r in probe}):
                group=[r for r in probe if int(r['role'])==role and int(r['threshold'])==threshold]
                result=dict(dataset=directory.name,role='initialization' if role else 'normal',threshold=threshold,frames=len(group))
                for key in ('candidates','selected','shortfall'):
                    result.update({key+'_'+k:v for k,v in describe([int(r[key]) for r in group]).items()})
                result.update({'empty_fraction_'+k:v for k,v in describe([int(r['empty_cells'])/(int(r['cell_cols'])*int(r['cell_rows'])) for r in group]).items()})
                thresholds.append(result)
    write(root/'candidate_unit_summary.csv',units);write(root/'fast_threshold_summary.csv',thresholds)
    # Correct derived CSV semantics; retain board facts and raw timing bytes.
    smoke=read(root/'results_b2_smoke.csv')
    for row in smoke:
        if row['variant']=='native':
            for key in row:
                if 'read_ms' in key or 'decode_ms' in key:row[key]=''
    write(root/'results_b2_smoke.csv',smoke)

def plots(root,manifest,matrix):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font=next((f.name for f in font_manager.fontManager.ttflist if f.name in ('Microsoft YaHei','SimHei','Noto Sans CJK SC')),None)
    if not font:raise RuntimeError('Chinese font unavailable; do not export illegible charts')
    plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'font.size':11})
    variants=list(manifest['plan']['variants']);colors=['#275d9f','#bd6219','#318565']
    fig,axes=plt.subplots(1,3,figsize=(16,5),sharey=True)
    for ax,d,color in zip(axes,manifest['datasets'],colors):
        rows=[r for r in matrix if r['dataset']==d['name']]
        for n,row in enumerate(rows):
            if row['finished_input']:ax.bar(n,float(row['ok_fraction'])*100,color=color)
            else:ax.axvspan(n-.4,n+.4,color='#ad2525',alpha=.06);ax.text(n,50,'超时\n无完整统计',rotation=90,ha='center',va='center',color='#ad2525')
        ax.set(title=label(d['name']),xticks=range(len(variants)),xticklabels=variants,ylim=(0,105));ax.tick_params(axis='x',rotation=45);ax.grid(axis='y',alpha=.2)
    axes[0].set_ylabel('OK 帧 / 全部输入帧（%）')
    fig.suptitle('B2 冒烟：固定前 600 帧，各配置一次；实拍为借用内参，未本机标定')
    fig.tight_layout();fig.savefig(root/'tracking_smoke.png',dpi=300);plt.close(fig)
    rows=read(root/'fast_threshold_summary.csv');fig,axes=plt.subplots(1,2,figsize=(12,5))
    for d,color in zip([d for d in manifest['datasets'] if d['kind']=='prepared'],colors):
        normal=sorted([r for r in rows if r['dataset']==d['name'] and r['role']=='normal'],key=lambda r:int(r['threshold']))
        init=sorted([r for r in rows if r['dataset']==d['name'] and r['role']=='initialization'],key=lambda r:int(r['threshold']))
        x=[int(r['threshold']) for r in normal]
        axes[0].plot(x,[float(r['candidates_median']) for r in normal],'-o',color=color,label=label(d['name']))
        axes[1].plot(x,[float(r['empty_fraction_median'])*100 for r in normal],'-o',color=color,label=label(d['name'])+' 正常档')
        axes[1].plot(x,[float(r['empty_fraction_median'])*100 for r in init],'--s',color=color,label=label(d['name'])+' 初始化档')
    axes[0].set(xlabel='FAST 阈值',ylabel='原图层候选点数（点/帧，中位数）')
    axes[1].set(xlabel='FAST 阈值',ylabel='G 空格比例（%，逐帧中位数）',ylim=(0,100))
    for ax in axes:ax.set_xticks([10,15,20,25]);ax.grid(alpha=.2);ax.legend(fontsize=9)
    fig.suptitle('Tello 全帧统计，960×720；基准 8 层公式的第 0 层预算')
    fig.tight_layout();fig.savefig(root/'fast_thresholds.png',dpi=300);plt.close(fig)

def report(root,state,manifest,matrix,attempts,evidence):
    units=read(root/'candidate_unit_summary.csv');thresholds=read(root/'fast_threshold_summary.csv')
    forecast=json.loads((root/'b3_duration_forecast.json').read_text(encoding='utf-8'))
    p1=next(r for r in matrix if '184929' in r['dataset'] and r['variant']=='P1')
    p2=next(r for r in matrix if '184929' in r['dataset'] and r['variant']=='P2')
    lines=['# B2 设计候选开发与冒烟报告','',
        '**开发、特征校核和全帧 FAST 统计完成；SLAM 冒烟 29/30 个矩阵槽位跑通，MIN 在 Tello 20:06:48 超时。因此“每个变体在三个数据集均跑通”尚未全部通过。B3 未启动。**','',
        '**B3预检勘误（2026-10-05）：** 源码检查发现B2生成器/参考使用lapping区间{0,0}，实际单目Frame使用{0,1000}，使特征数组顺序不同。旧V0抽检未覆盖这一调用差异，不能证明与native实际输入等价；本报告保留旧运行事实，不能把旧链路的相对差异当作修复后消融结论。详见docs/B3_PRECHECK.md。修复后逐帧及重复运行验收尚未完成。native read/decode衍生CSV已改为空值；raw不改。','',
        '每段固定前 600 帧、各配置一次，仅用于流程与初始化冒烟。MH01 为 752×480，Tello 为 960×720；实拍一律为**借用内参，未本机标定**，没有真值，不能表述绝对精度或真实尺度。候选不是已定型 FPGA 规格；没有带入 panorama Demo 参数。','',
        '## 证据与运行条件','',
        f'共 {evidence["attempt_records"]} 条记录：30 个原槽位，加两次输入故障恢复验证；{evidence["successful_complete_attempts"]} 次完整跑完 600 帧并成功初始化。原 B 读取失败、原 MIN 特征生成失败均保留，恢复运行使用新目录。MIN 恢复运行超时失败，没有补跑挑选结果。',
        f'归档及 {evidence["raw_manifest_files"]} 个文件（{evidence["raw_manifest_bytes"]:,} 字节）SHA256 校验通过；成功运行的核心指标已从 raw 单独复算，与板上统计一致。CPU4–7 A76、CPU/DMC performance（DMC 1560 MHz）、无 Viewer、保留实时节奏。未检测到降频；采样全部温度传感器最高 {evidence["max_all_sensors_c"]:.3f} ℃；运行后 governor 恢复，板上无遗留 mono_euroc。',
        '输入故障已证实为单张 PNG 页缓存中 6 个单比特错误，磁盘原图正确；缓存核验后两段全部 3957 张图片通过 SHA256，批次结束后再次全量通过。DDR/RAM稳定性根因尚未验证，报告不把“无降频”等同于内存稳定性证明。','',
        '## 代码与单元验收','',
        '独立 CPU 生成器只改变前端，沿用 B1 小端版本化特征格式；跟踪、匹配旋转直方图、建图/优化未改。已验收 SLAM 程序和库不重编，哈希不变。补丁0011及代码/配置分别在 Git 分支 b2/design-candidates 保留。原版参考来自未修改 C1 源码，以不同命名空间编译；全部变体使用标准 bit_pattern_31_。',
        'P1=1层；P2=2层、scaleFactor2、2×2平均向下截断；F=固定FAST20；G=预算推导格子/每格1强点/无回填；A8/A32=最近中心角同时用于描述子与输出角（旧V2b）；B=去描述子高斯；MIN=P1+F+G+A8+B。P2舍入可配置为半入，B3前可调整。正常N1000，初始化N5000；P2预算667/333与3333/1667。','',
        '独立合成检查20个角度、4个网格边界/同分/截断/空格案例、40个平均像素、6个预算组合通过；实图开发门禁27组、108包通过。冒烟特征文件全帧头/坐标/层分布/size/分数/量化角检查通过，原版每100帧抽检与内存快照比较。V0三段抽检关键点/描述子逐字节一致。','',
        '同关键点汉明比较在候选自身同层图像、整数坐标处重新计算原版连续IC+高斯+BRIEF。P1/P2/F/G均为0；P2改变了层像素，组件汉明0不代表完整前端等价。']
    table(lines,['数据','A8 中位/P95（bit）','A32 中位/P95（bit）','B 中位/P95（bit）','MIN 中位/P95（bit）'],
        [[label(d['name'])]+[next(formatted(float(r['hamming_median']),0)+' / '+formatted(float(r['hamming_p95']),0) for r in units if r['dataset']==d['name'] and r['variant']==v) for v in ('A8','A32','B','MIN')] for d in manifest['datasets']])
    lines+=['','## SLAM 冒烟结果','',
        '初始化帧为1起算；OK比例分母为全部600帧，包括初始化前帧。另给首次OK之后的OK比例，避免把初始化等待误算成后续跟踪丢失。失败指标留“未完成”，不填0。表中B/20:06:48为输入恢复验证，原失败仍在 attempts_verified.csv。']
    for d in manifest['datasets']:
        lines+=['','### '+label(d['name'])+('（借用内参，未本机标定）' if d['kind']=='prepared' else '')]
        table(lines,['候选','跑完','初始化帧','OK比例','初始化后OK','丢失段','地图数'],
            [[r['variant'],'是' if r['finished_input'] else '超时',formatted(r['initialization_frame'],0),formatted(r['ok_fraction'],2,True),formatted(r['post_initialization_ok_fraction'],2,True),formatted(r['loss_segments'],0),formatted(r['maps'],0)] for r in matrix if r['dataset']==d['name']])
    lines+=['','## 耗时与点数','',
        '下表仅正常跟踪帧，报告 Total−完整特征槽的剩余线程耗时；inject读文件/解码另列在CSV。模拟器的CPU提取耗时不作为FPGA性能。部分候选丢失严重、可计时的正常帧少，较低剩余耗时不能直接当作可用加速。每组只有一次，不给五次中位数或正式速度结论。']
    table(lines,['数据','native剩余中位（ms）','V0剩余中位（ms）','V0剩余P95（ms）','V0读/解码中位（ms）','V0正常点数中位'],
        [[label(d['name']),formatted(next(r['normal_remaining_median_ms'] for r in matrix if r['dataset']==d['name'] and r['variant']=='native'),3)]+[
            formatted(next(r[key] for r in matrix if r['dataset']==d['name'] and r['variant']=='V0'),3 if key!='normal_points_median' else 0)
            for key in ('normal_remaining_median_ms','normal_remaining_p95_ms')]+[
            next(formatted(r['normal_read_median_ms'],3)+' / '+formatted(r['normal_decode_median_ms'],3) for r in matrix if r['dataset']==d['name'] and r['variant']=='V0'),
            next(formatted(r['normal_points_median'],0) for r in matrix if r['dataset']==d['name'] and r['variant']=='V0')]
         for d in manifest['datasets']])
    lines+=['','全部候选的点数、内点、剩余耗时中位/P95见 matrix_verified.csv；这些是成功帧的样本统计，不是FPGA实测。','',
        '## FAST额外统计','',
        '18:49:29统计2273帧，20:06:48统计1684帧。原图层正常预算217、初始化预算1086；格子边54/24像素，对应204/1064格。余数并入末行/列。候选点数两档相同，G的空格/选中按各档重新计算。以下均为逐帧中位数，不改变F=20。']
    table(lines,['数据','阈值','候选点数/帧','正常空格','初始化空格','正常选中/初始化选中'],
        [[label(d['name']),t,formatted(float(n['candidates_median']),1),formatted(float(n['empty_fraction_median']),2,True),formatted(float(init['empty_fraction_median']),2,True),formatted(float(n['selected_median']),1)+' / '+formatted(float(init['selected_median']),1)]
         for d in manifest['datasets'] if d['kind']=='prepared' for t in (10,15,20,25)
         for n in [next(r for r in thresholds if r['dataset']==d['name'] and r['role']=='normal' and int(r['threshold'])==t)]
         for init in [next(r for r in thresholds if r['dataset']==d['name'] and r['role']=='initialization' and int(r['threshold'])==t)]])
    lines+=['','## MIN超时证据与局限','',
        '20:06:48恢复运行的日志先后显示 `New Map created with 104 points`、多次 `Fail to track local map!`、`SYSTEM-> Reseting active map in monocular case`、`96 Frames set to lost`、再初始化194点后再次跟踪失败。30分钟监督器终止运行，原文为 `MH01 exceeded 30-minute per-attempt limit`（这是通用监督器旧的固定报错文字，实际数据为Tello）。',
        'FeatureTimeStats.csv持久化了122行，最后一行为frame_index121、timestamp_ns5039310300，表明至少122次TrackMonocular调用返回。TrackingStates.csv和MapStateStats.csv仍空，受ofstream缓冲及强制终止影响；缺少完整跟踪计时、最终Atlas、轨迹，因此OK占比、地图数和最终耗时均未完成。日志显示重置，但不能编造最终地图数。未保存当时线程栈，具体阻塞线程/原因未完成；不能据此断言死锁或再次内存位错误。',
        'MIN前端特征文件生成和校核通过；这次失败位于SLAM回放阶段。没有再次PNG CRC报错或降频记录。后续应保留超时现场状态/等待点，不通过更换种子、重跑挑选来掩盖问题。','',
        '## 当前结论与B3计划','',
        f'- 单层P1、两层P2在18:49:29初始化后OK分别为{formatted(p1["post_initialization_ok_fraction"],2,True)}和{formatted(p2["post_initialization_ok_fraction"],2,True)}；该单次前缀显示少层候选有跟踪风险，不能只看耗时。',
        '- 去模糊B在18:49:29出现持续丢失；20:06:48恢复验证初始化延迟到251帧，初始化后该短前缀保持OK。不能把两个不同现象都归因于持续跟踪失败。',
        '- MIN在18:49:29仅6.83%全帧为OK，20:06:48超时，完整组合目前有明显可用性问题。',
        '- F和G两段实拍初始化后本次均保持OK，G点数较少、初始化较晚；A8本次未出现丢失，A32有短丢失。但A8/A32排序不能据单次结果下结论；V0/20:06:48也有两段短丢失，体现多线程/短前缀波动。',
        '- A8描述子变化大于A32是直接特征证据；能否影响词袋重定位、回环和完整轨迹，必须留给正式B3。EuRoC为全局快门灰度，与Tello卷帘/H.264不同，不能直接外推。','',
        f'第一轮仍按用户矩阵 native/V0/P1/P2/F/G/A8/A32/B/MIN ×3×5=150次；第二轮待用户选推荐组合，另15次。基础排程预测为{forecast["total_forecast_h"]:.2f}小时（SLAM约{forecast["slam_forecast_s"]/3600:.2f}h，生成约{forecast["feature_generation_linear_forecast_s"]/3600:.2f}h），未含校验/冷却。若仅MIN/20:06:48五次均触发30分钟超时，按同口径约9.7h；这是条件预测，不是实验数字。全帧特征库预计{forecast["full_corpus_packet_bytes_forecast"]/1024**3:.2f}GiB，板上当前24GiB可用，需另留审计与日志空间。',
        'batch_b3.py与evaluate_b3.py已准备：序号轮转、新native五次、失败不替换、CPU/DMC条件和恢复、Tello公共OK帧Sim3归一化形状差异/native自身重复范围、MH01 evo+NumPy ATE。B3正式结果未完成，本阶段不声称“无可测差异”。',
        '**强制丢失方案只供审阅，未实现：** MH01首帧起第90秒跳过[90,92)秒图像，保留原时间戳/等待，各候选五次、无跳帧对照。确认跳前OK、实际非OK、是否回原map_id、relocalized标志与恢复帧数；未触发就记未触发。批准后另50次，不计150次。',
        '下一阶段需用户确认：是否按原10候选进入B3，并先强化MIN超时现场诊断、检查内存稳定性；保持FPGA设计候选和借用内参标注。B2在此停下，B3未启动。','',
        '## 重现','',
        '```powershell','. ..\\..\\scripts\\project_env.ps1','& $ProjectPython scripts/report_b2.py --batch B2_design_smoke_01','```','',
        'raw保留板上字节，所有CSV/报告从raw重算；不把原失败替换成恢复成功。构建/变体/恢复实现分别见0011补丁、tools/b2_candidates、configs/b2/design_candidates.json和B2_RUNBOOK.md。',
        '验收：编译/前端单元/文件格式/全帧FAST通过；29个冒烟槽位通过、1个MIN槽位失败；五次统计、完整ATE、重定位、FPGA性能均属B3，未完成。']
    (root/'B2_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);a=p.parse_args();root=ROOT/'reports/b2'/a.batch
    state,manifest,matrix,attempts,evidence=recompute(root);regenerate_frontend_summaries(root,state)
    report(root,state,manifest,matrix,attempts,evidence);plots(root,manifest,matrix)
    print('B2_REPORT_REBUILT slots=%d pass=%d failed=%d raw_files=%d'%(len(matrix),evidence['matrix_successes'],len(matrix)-evidence['matrix_successes'],evidence['raw_manifest_files']))
if __name__=='__main__':main()
