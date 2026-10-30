"""Prepare a paired150MHz source/report/bit publication; preserve old releases."""
import argparse
from pathlib import Path
import re
import subprocess
from prepare_integrated4_publication import copy,read,selected,sha,tree,write


def main():
    p=argparse.ArgumentParser()
    for name in ('root','repo','pair','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();root=a.root.resolve();orb=root/'orb60';repo=a.repo.resolve();pair=a.pair.resolve()
    assert repo.is_relative_to(root/'repos') and (repo/'.git').is_dir()
    assert subprocess.check_output(['git','-C',str(repo),'branch','--show-current'],text=True).strip()=='codex/orb60-4ppc'
    assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True).strip(),'Preserve other checkout edits'
    bit=read(pair/'bit/status.json');validation=read(pair/'bit/release_validation.json');joint=read(pair/'joint_result.json')
    assert bit['State']=='SUCCEEDED' and bit['Stage']=='COMPLETE'
    assert validation['status']==joint['status']=='PASS' and validation['frequency_mhz']==150
    assert sha(pair/'bit/orb60_150mhz.bit')==bit['BitSha256'].lower()
    origins={kernel:Path(read(pair/'status.json')[key]) for kernel,key in (('layer2','LayerHlsJob'),('descriptor','DescriptorHlsJob'))}
    prefix=Path('FPGA_ORB_HLS/fastv2/next');front=origins['layer2']/'inputs'/prefix;desc=origins['descriptor']/'inputs'/prefix
    # Pair the actually compiled backend closure; unused descriptor CPP in the
    # frontend snapshot may differ, and is replaced with the accepted backend.
    pending=[Path('src/descriptor_hls.cpp')];closure=set()
    while pending:
        rel=pending.pop()
        if rel in closure:continue
        closure.add(rel)
        if rel!=Path('src/descriptor_hls.cpp'):assert sha(front/rel)==sha(desc/rel),str(rel)
        for name in re.findall(r'#include\s+"([^"]+)"',(desc/rel).read_text(encoding='utf-8-sig')):
            found=[x for x in (rel.parent/name,Path('include')/name,Path('src')/name) if (desc/x).is_file()]
            assert found,'Unresolved backend include:'+name
            pending.append(found[0])
    author=repo/'orb60/experiments/frequency_speed_joint'
    assert not author.exists(),'Preserve an existing published variant'
    tree(origins['layer2']/'inputs/FPGA_ORB_HLS',author/'FPGA_ORB_HLS')
    tree(origins['layer2']/'inputs/FPGA_ORB_SHARED_v1.0',author/'FPGA_ORB_SHARED_v1.0')
    for rel in closure:copy(desc/rel,author/prefix/rel)
    for name in ('front_vectors.inc','layer2_vectors.inc'):copy(origins['layer2']/'inputs'/name,author/name)
    a32_test=orb/'experiments/frequency_tree_read/test_a32_quantize.cpp'
    if a32_test.is_file():copy(a32_test,author/'test_a32_quantize.cpp')
    for folder in ('scripts','tests','vivado','docs'):tree(orb/folder,repo/'orb60'/folder)
    selected(orb,repo/'orb60',['WORKFLOW.md','AGENTS.md'])
    destination=repo/'orb60/artifacts/speed_joint_150mhz'
    selected(pair/'bit',destination,['orb60_150mhz.bit','status.json','joint_validation.json','release_validation.json','bit_check_timing.rpt','bit_route_status.rpt','bit_drc.rpt'])
    write(destination/'artifact_manifest.json',dict(status='PASS',part='xc7z015clg485-2',frequency_mhz=150,layer_ppc=4,
        ps_fclk_input_mhz=100,bit_sha256=bit['BitSha256'].lower(),checkpoint_sha256=validation['checkpoint_sha256'],
        physical_board_verified=False,ps_modified=False,release_validation=validation,backend_source_closure=[x.as_posix() for x in sorted(closure)],
        build_flags=dict(layer=dict(LayerPpc=4,FastStaged=True,LayerIoOverlap=True,LayerBramFifos=True,SliceCompactMode=2),
            descriptor=dict(DescriptorWidthMode=2,DescriptorPrefetch=8,DescriptorPatch32=True,DescriptorMomentFusion=1,DescriptorFastQuantize=1))))
    evidence=repo/'orb60/evidence/speed_joint_150mhz'
    for kernel,origin in origins.items():
        frozen=repo/'orb60/frozen/speed_joint_150mhz'/kernel
        for record in read(origin/'source_manifest.json'):
            assert sha(origin/'inputs'/record['Path']).upper()==record['SHA256']
            copy(origin/'inputs'/record['Path'],frozen/'inputs'/record['Path'])
        selected(origin,frozen,['status.json','source_manifest.json','hls.tcl'])
        tree(origin/f'projects/{kernel}/solution1/syn/report',evidence/'hls'/kernel)
        selected(origin/f'projects/{kernel}/solution1/sim/report',evidence/'hls'/kernel,[f'fastv2_{kernel}_hls_cosim.rpt'])
        for header in (origin/f'projects/{kernel}/solution1/impl/ip/drivers/fastv2_{kernel}_hls_v1_0/src').glob('*_hw.h'):
            copy(header,evidence/'registers'/header.name)
    route=Path(joint['route']);frame=Path(joint['frame']);protocol=Path(joint['protocol']);board=Path(validation['board_4gb'])
    tree(route/'reports',evidence/'route');selected(route,evidence/'route',['status.json','tool_manifest.json'])
    tree(route/'inputs',evidence/'route/inputs')
    for label,job in (('native',frame),('board_4gb',board),('protocol',protocol)):
        selected(job,evidence/label,['status.json','performance.json','rtl_manifest.json','test_manifest.json','profile_manifest.json','delay_audit.json'])
        tree(job/'inputs',evidence/label/'inputs')
    for kernel in origins:selected(protocol/kernel,evidence/'protocol'/kernel,['result.json','status.json','config.json','rtl_manifest.json'])
    selected(pair,evidence,['status.json','joint_result.json','structure_comparison.json'])
    for name in ('board_4gb_comparison','row_4gb_comparison','frame_comparison'):
        if (pair/name).exists():tree(pair/name,evidence/name)
    fixture=repo/'orb60/fixtures/speed_joint'
    benchmark=Path(read(frame/'status.json')['BenchmarkJob'])
    tree(benchmark/'vectors',fixture/'benchmark/vectors');copy(benchmark/'status.json',fixture/'benchmark/origin_status.json')
    tree(origins['descriptor']/'descriptor_vectors',fixture/'descriptor_vectors')
    resources=joint['routed_resources'];primary=validation['sufficient_bandwidth_frames']
    lines=['# R11 ORB：150MHz吞吐优化交付','',
        '固定960×720、8层、xc7z015clg485-2；4PPC图像核与精确方向/BRIEF核。',
        '性能选择按用户指定的4GB/s充足带宽、无合成随机停顿、0–50ns首读。',
        '像素、点数与排序、方向/A32、描述子和64字节记录保持逐字节一致。','',
        '## 实测电脑门禁','',
        '| 输入 | 整帧RTL耗时/ms | 等效FPS |','|---|---:|---:|']
    for item in primary:
        label={280:'普通280点',942:'压力942点',0:'空点'}[item['points']]
        lines.append(f"| {label} | {item['milliseconds']:.5f} | {item['equivalent_fps']:.2f} |")
    lines+=['','这是两核真实RTL共享DDR模型的结果，不是板上视频帧率。',
        '4GB/s是用户提供的可用带宽预算，HP/仲裁限制仍存在于模型中。',
        '其他DDR停顿配置保持功能回归与诊断；不用于选择性能候选。','',
        '## 完整路由','',
        f"WNS **{joint['wns_ns']:+.3f}ns**，WHS **{joint['whs_ns']:+.3f}ns**；TNS/THS为零。",
        'Setup/hold、时钟与约束覆盖、完整路由及严格DRC均通过。','',
        '| 资源 | 已用/总量 | 利用率 |','|---|---:|---:|']
    for key,label in (('lut','LUT'),('ff','FF'),('bram_tile','BRAM tile'),('dsp','DSP'),('slice','Slice')):
        item=resources[key];lines.append(f"| {label} | {item['used']}/{item['total']} | {item['percent']:.2f}% |")
    lines+=['','## 保留的优化','',
        '- FAST/NMS窗口每行并行初始化，去除旧串行清零循环。',
        '- 方向矩按原row/word顺序连续接收，窄化计数器；避免31个行循环的串行等待。',
        '- 锦标赛BRAM增加读取寄存器；node255..2保持II=2，根节点在循环排空后更新。',
        '  真实RAW distance2经逐bank/address枚举证明，不隐藏依赖或增加时序例外。','',
        '新前端21个C/RTL事务通过；相同SHA后端的38个C/RTL及6个随机协议事务',
        '按配对记录复用。新前端随机AXI/复位/完成屏障、12个原生整帧、',
        '12个4GB/s整帧和3帧旧模型重放精确通过。完整top重新路由。','',
        '## 源码、产物与复现','',
        '- [源码](../experiments/frequency_speed_joint/FPGA_ORB_HLS/fastv2/next/src/)',
        '- [逐核冻结输入](../frozen/speed_joint_150mhz/)',
        '- [150MHz bit](../artifacts/speed_joint_150mhz/orb60_150mhz.bit)',
        '- [完整时序](../evidence/speed_joint_150mhz/route/post_route_timing.rpt)',
        '- [完整资源](../evidence/speed_joint_150mhz/route/post_route_utilization.rpt)',
        '- [4GB/s精确整帧](../evidence/speed_joint_150mhz/board_4gb/performance.json)',
        '- [相同150MHz/DDR对照](../evidence/speed_joint_150mhz/board_4gb_comparison/SUMMARY_ZH.md)','',
        '```powershell',
        'pwsh -NoProfile -File tools/verify_integrated4.ps1',
        'pwsh -NoProfile -File orb60/scripts/verify_speed150.ps1',
        'pwsh -NoProfile -File orb60/scripts/reproduce_speed150.ps1 -Mode Inputs',
        'pwsh -NoProfile -File orb60/scripts/reproduce_speed150.ps1 -Mode All',
        '```','',
        'All入口重新生成本版150MHz HLS/RTL、协议、整帧、完整route与bit；耗时较长。',
        '不需要重新测试125MHz，仅读取其已发布寄存器定义验证接口一致。',
        '新bit的MMCM要求PS FCLK输入100MHz，内部核为150MHz。',
        'PS/BSP/ELF/XSA及板上验证仍暂停，原三核ELF不能视作这版bit的配套软件。',
        '本交付未进行任何JTAG/非易失编程。','',
        f"Bit SHA256：`{bit['BitSha256'].lower()}`。"]
    (repo/'orb60/docs/SPEED150_RELEASE_RESULTS_ZH.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    readme=repo/'README.md';text=readme.read_text(encoding='utf-8-sig')
    text=text.replace('# R11 ORB：4PPC／100与125MHz整合优化','# R11 ORB：4PPC／150MHz吞吐优化')
    text=text.replace('125MHz是本轮最快候选。','150MHz吞吐优化版现已通过完整电脑门禁并附带bitstream。')
    text=text.replace('当前交付**通过完整电脑门禁的4PPC／100与125MHz版本**','保留**通过完整电脑门禁的4PPC／100与125MHz版本**')
    marker='## 完整路由结果'
    summary=['## 最新150MHz交付','',
        '[源码/bit/时序/资源/性能与复现说明](orb60/docs/SPEED150_RELEASE_RESULTS_ZH.md)。',
        f"完整路由WNS {joint['wns_ns']:+.3f}ns、WHS {joint['whs_ns']:+.3f}ns；TNS/THS为零。",
        f"4GB/s充足带宽下普通图{primary[0]['milliseconds']:.3f}ms/{primary[0]['equivalent_fps']:.2f}FPS，压力942点{primary[1]['milliseconds']:.3f}ms/{primary[1]['equivalent_fps']:.2f}FPS。",
        '数值为真实RTL仿真，板上视频/PS仍待验证；旧100/125MHz产物保留。',
        '150MHz bit要求PS FCLK输入100MHz；原R11三核ELF不配对。','',marker]
    assert marker in text
    text=text.replace(marker,'\n'.join(summary),1)
    text=text.replace('- [本版源码]',
        '- [150MHz源码](orb60/experiments/frequency_speed_joint/FPGA_ORB_HLS/fastv2/next/src/)、[150MHz bit](orb60/artifacts/speed_joint_150mhz/orb60_150mhz.bit)、[150MHz完整证据](orb60/evidence/speed_joint_150mhz/)。\n- [保留100MHz源码]',1)
    text=text.replace('## 完整路由结果','## 保留100/125MHz路由结果',1)
    text=text.replace('## 整帧RTL性能','## 保留100/125MHz整帧RTL性能',1)
    text=text.replace('## 复现与校验','## 保留100/125MHz复现与校验',1)
    readme.write_text(text,encoding='utf-8')
    ignore=repo/'.gitignore';rule='!orb60/artifacts/speed_joint_150mhz/*.bit'
    text=ignore.read_text(encoding='utf-8-sig')
    if rule not in text:ignore.write_text(text.rstrip()+'\n'+rule+'\n',encoding='utf-8')
    write(a.output/'prepared.json',dict(status='PREPARED',pair=str(pair),repository=str(repo),bit_sha256=bit['BitSha256'].lower()))
    print('SPEED150_SOURCE_REPORT_BIT_PREPARED')


if __name__=='__main__':main()
