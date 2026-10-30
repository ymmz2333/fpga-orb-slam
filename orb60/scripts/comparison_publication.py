"""Refresh the complete 100 MHz ZIP with the concluded, failed 125 MHz study."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

from finish_publication import BRANCH, files, git, sha, write_json


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def route_metrics(job):
    state = read_json(job/'status.json')
    assert state['State'] == 'FAILED' and state['FrequencyMHz'] == 125
    assert state['Timing']['part'] == 'xc7z015clg485-2'
    assert float(state['Timing']['setup_REQUIREMENT']) == 8
    timing = (job/'reports/post_route_timing.rpt').read_text()
    table = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*'
                      r'(-?[\d.]+)\s+(-?[\d.]+)\s+(\d+)\s+\d+\s+'
                      r'(-?[\d.]+)\s+(-?[\d.]+)', timing, re.S)
    assert table, 'Missing actual setup/hold table'
    wns, tns, failed, whs, ths = table.groups()
    assert float(wns) == float(state['Timing']['wns_ns']) < 0
    assert float(whs) == float(state['Timing']['whs_ns']) >= 0 and float(ths) == 0
    coverage = (job/'reports/post_route_check_timing.rpt').read_text()
    counts = re.findall(r'^\d+\. checking \w+ \((\d+)\)', coverage, re.M)
    assert len(counts) == 24 and all(int(n) == 0 for n in counts)
    routing = (job/'reports/post_route_route_status.rpt').read_text()
    def nets(label):
        found = re.search(label+r'[. \t]*:[ \t]*(\d+)', routing)
        assert found
        return int(found.group(1))
    routed = nets('# of fully routed nets')
    assert routed == nets('# of routable nets') and nets('# of nets with routing errors') == 0
    drc = (job/'reports/post_route_drc.rpt').read_text()
    assert not re.search(r'^\|[^|]+\|\s*(Error|Critical Warning)\s*\|', drc, re.M)
    resources = (job/'reports/post_route_utilization.rpt').read_text()
    def used(label):
        found = re.search(r'^\| '+re.escape(label)+r'\s*\|\s*(\d+)\s*\|', resources, re.M)
        assert found, label
        return int(found.group(1))
    assert (job/'reports/post_route_clocks.tsv').read_text().strip() == 'clk_fpga_0\t8.000'
    return dict(job=job.name, status='FAILED_SETUP', wns_ns=float(wns),
                tns_ns=float(tns), failing_endpoints=int(failed), whs_ns=float(whs),
                ths_ns=float(ths), lut=used('Slice LUTs'), ff=used('Slice Registers'),
                bram=used('Block RAM Tile'), dsp=used('DSPs'), routed_nets=routed,
                worst_path=state['Timing'])


def publish(a):
    root, repo, out = a.root.resolve(), a.repo.resolve(), a.output.resolve()
    orb = root/'orb60'
    assert git(repo, 'branch', '--show-current').stdout.strip() == BRANCH
    assert not git(repo, 'diff', '--cached', '--name-only').stdout.strip(), 'Unexpected staged changes'
    if a.resume_worktree:
        touched = set(git(repo, 'diff', '--name-only', '-z').stdout.strip('\0').split('\0'))
        touched.update(git(repo, 'ls-files', '--others', '--exclude-standard', '-z').stdout.strip('\0').split('\0'))
        allowed = {'', 'orb60/WORKFLOW.md', 'orb60/README_ZH.md', 'orb60/PUBLICATION_MANIFEST.json',
                   'orb60/docs/125MHZ_COMPARISON_ZH.md', 'orb60/scripts/comparison_publication.py',
                   'orb60/scripts/post_route_physopt.ps1', 'orb60/vivado/post_route_physopt.tcl'}
        assert all(n in allowed or n.startswith('orb60/evidence/125mhz/') for n in touched), touched
    else:
        assert not git(repo, 'status', '--porcelain').stdout.strip(), 'Publication worktree must be clean'
    prior = read_json(a.prior/'publication_result.json')
    original_zip = Path(prior['zip'])
    assert sha(original_zip) == read_json(a.prior/'zip_manifest.json')['sha256']
    bit_info = read_json(repo/'orb60/artifacts/100mhz/artifact_manifest.json')
    assert bit_info['status'] == 'PASS' and not bit_info['ps_firmware_modified']
    assert sha(repo/'orb60/artifacts/100mhz/orb60_100mhz.bit') == bit_info['bit_sha256']
    out.mkdir(parents=True, exist_ok=False)
    rows = [route_metrics(job) for job in a.timing]
    assert len(rows) == 3
    evidence = repo/'orb60/evidence/125mhz'
    for row, job in zip(rows, a.timing):
        name = job.name
        copy_file(job/'status.json', evidence/name/'status.json')
        for p in (job/'reports').iterdir():
            if p.is_file() and p.suffix in ('.rpt', '.tsv', '.xdc'):
                copy_file(p, evidence/name/'reports'/p.name)
        for p in (job/'inputs').iterdir():
            if p.is_file() and p.suffix in ('.tcl', '.ps1', '.json'):
                copy_file(p, evidence/name/'inputs'/p.name)
    first_state = read_json(a.timing[0]/'status.json')
    for kernel, key in (('layer2', 'LayerHlsJob'), ('descriptor', 'DescriptorHlsJob')):
        hls = Path(first_state[key])
        hs = read_json(hls/'status.json')
        assert hs['State'] == 'SUCCEEDED' and hs['Cosim'] and hs['PeriodNs'] == 8
        for name in ('status.json', 'source_manifest.json', 'hls.tcl'):
            copy_file(hls/name, evidence/'hls'/kernel/name)
        for folder, name in (('syn', 'csynth.xml'), ('syn', 'csynth.rpt'), ('sim', 'cosim.rpt')):
            p = hls/f'projects/{kernel}/solution1/{folder}/report/fastv2_{kernel}_hls_{name}'
            copy_file(p, evidence/'hls'/kernel/p.name)
        accepted = Path(first_state['AcceptedLayer' if kernel == 'layer2' else 'AcceptedDescriptor'])
        for name in ('status.json', 'comparison.json'):
            copy_file(accepted/name, evidence/'hls'/kernel/'acceptance'/name)
    summary = dict(scope='Failed 125 MHz bounded timing comparison; retained bit is accepted 100 MHz',
                   physical_pass_limit=2, results=rows, ps_firmware_modified=False,
                   physical_board_verified=False, accepted_125mhz=False)
    write_json(evidence/'comparison.json', summary)
    for name in ('post_route_physopt.ps1', 'comparison_publication.py'):
        copy_file(orb/'scripts'/name, repo/'orb60/scripts'/name)
    copy_file(orb/'vivado/post_route_physopt.tcl', repo/'orb60/vivado/post_route_physopt.tcl')
    copy_file(orb/'WORKFLOW.md', repo/'orb60/WORKFLOW.md')
    table = '\n'.join(f'| {label} | {r["wns_ns"]:+.3f} | {r["tns_ns"]:+.3f} | '
                      f'{r["failing_endpoints"]} | {r["whs_ns"]:+.3f} | {r["lut"]} |'
                      for label, r in zip(('8 ns HLS 完整路由', 'AggressiveExplore', 'Explore'), rows))
    note = ('# 125 MHz 有界对照实验：未通过\n\n'
            '两个核均从配对源码重新按 8 ns 目标完成 HLS、精确 C/RTL co-sim 和 II/64-bit 接口检查，'
            '随后对 xc7z015clg485-2 的完整顶层进行实际布局布线。\n\n'
            '| 阶段 | WNS/ns | TNS/ns | 失败端点 | WHS/ns | LUT |\n'
            '|---|---:|---:|---:|---:|---:|\n'+table+'\n\n'
            '最终 FF 29,048、BRAM tile 68/95、DSP 40/160；51,283 个可路由网络全部布通，'
            '无路由错误，12 类 check_timing 计数均为零，DRC 无 Error/Critical Warning。'
            '这些检查不能抵消负 WNS，125 MHz 仍未签核。\n\n'
            '最后一轮只改善 5 ps，有界物理实验到此结束。热点仍是候选筛选器'
            'best_score 读选择、比较到另一分数寄存器 CE 的反馈路径。后续提频需另做 HLS 结构优化'
            '并重跑功能、协议和完整路由门禁。\n\n'
            '本 ZIP 的可交付 bitstream 仍是原已通过的 100 MHz 版本，WNS +0.238 ns、'
            'WHS +0.035 ns，bit 和冻结配对源码字节不变。PS 工作按用户要求暂缓，'
            '没有配套新 ELF/XSA，也不能使用旧三核 ELF 配置新两核 bit。125 MHz 整帧和板上 FPS 未实测。\n\n'
            '证据见 ../evidence/125mhz/；复现入口为 scripts/frequency_gate.ps1 和 '
            'scripts/post_route_physopt.ps1。各 job 下保留当次输入、真实报告和 FAILED 状态。\n')
    (repo/'orb60/docs/125MHZ_COMPARISON_ZH.md').write_text(note, encoding='utf-8', newline='')
    readme = repo/'orb60/README_ZH.md'
    text = readme.read_text(encoding='utf-8')
    addition = ('\n## 125 MHz 对照结果\n\n'
             '实际 8 ns HLS 重建和两轮物理优化后，最终 WNS −0.034 ns、WHS +0.050 ns，'
             '仍未通过 setup。100 MHz bit 与配对源码保持不变，PS 工作暂缓。'
             '完整记录见 [125 MHz 对照说明](docs/125MHZ_COMPARISON_ZH.md)。\n')
    if '## 125 MHz 对照结果' in text:
        assert a.resume_worktree and text.endswith(addition), 'Unexpected existing comparison note'
    else:
        text += addition
    readme.write_text(text, encoding='utf-8', newline='')
    manifest = repo/'orb60/PUBLICATION_MANIFEST.json'
    published = files(repo)
    write_json(manifest, dict(scope='Source/docs/evidence and accepted 100 MHz bit; failed 125 MHz comparison',
        files=[dict(path=p.relative_to(repo).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
               for p in published if p != manifest]))
    shell = shutil.which('pwsh') or shutil.which('powershell')
    assert shell, 'A PowerShell runtime is required for the unmodified integrity gate'
    verify = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(repo/'tools/verify_orb60.ps1')], capture_output=True, text=True)
    (out/'verify_publication.log').write_text(verify.stdout+verify.stderr, encoding='utf-8')
    assert verify.returncode == 0, verify.stderr
    prefix = 'fpga-orb-r11/'
    with zipfile.ZipFile(original_zip) as archive:
        assert archive.testzip() is None
        payload = {n:archive.read(n) for n in archive.namelist()
                   if not n.endswith('ZIP_CONTENT_MANIFEST.json')}
    payload.update({prefix+p.relative_to(repo).as_posix():p.read_bytes() for p in published})
    zip_rows = [dict(path=n[len(prefix):], bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                for n, data in sorted(payload.items())]
    zip_path = out/'orb60_100mhz_source_bit_with_125mhz_comparison.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(payload.items()): archive.writestr(name, data)
        archive.writestr(prefix+'ZIP_CONTENT_MANIFEST.json', json.dumps(dict(files=zip_rows), indent=2)+'\n')
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None and len(archive.namelist()) == len(set(archive.namelist()))
        for row in zip_rows:
            assert hashlib.sha256(archive.read(prefix+row['path'])).hexdigest() == row['sha256']
        for kernel in ('layer2', 'descriptor'):
            origin = prefix+f'orb60/frozen/100mhz/{kernel}/'
            for row in json.loads(archive.read(origin+'source_manifest.json').decode('utf-8-sig')):
                assert hashlib.sha256(archive.read(origin+'inputs/'+row['Path'].replace('\\','/'))).hexdigest().upper() == row['SHA256']
        assert hashlib.sha256(archive.read(prefix+'orb60/artifacts/100mhz/orb60_100mhz.bit')).hexdigest() == bit_info['bit_sha256']
    spec = out/'git_pathspec.bin'
    spec.write_bytes(b'\0'.join((':(literal)'+p.relative_to(repo).as_posix()).encode('utf-8')
                               for p in published)+b'\0')
    staged = git(repo, 'add', '--pathspec-from-file='+str(spec), '--pathspec-file-nul')
    assert staged.returncode == 0, staged.stderr
    allowed = {p.relative_to(repo).as_posix() for p in published}
    assert set(git(repo, 'diff', '--cached', '--name-only', '-z').stdout.strip('\0').split('\0')) <= allowed
    message = out/'commit_message.txt'
    message.write_text('Record concluded 125 MHz timing comparison and physical optimization\n\n'
                       'Publish the actual 8 ns HLS and full-top reports and reproducible\n'
                       'bounded physical scripts. WNS improves -0.341 -> -0.039 -> -0.034 ns\n'
                       'but setup remains failing; retain the accepted 100 MHz bit/source.\n'
                       'PS integration and physical-board validation remain deferred.\n', encoding='utf-8')
    committed = git(repo, 'commit', '--file', str(message))
    assert committed.returncode == 0, committed.stderr
    result = dict(status='ZIP_READY', branch=BRANCH, commit=git(repo,'rev-parse','HEAD').stdout.strip(),
                  zip=str(zip_path), zip_bytes=zip_path.stat().st_size, zip_sha256=sha(zip_path),
                  payload_files=len(zip_rows), frozen_inputs_verified=True,
                  accepted_bit_sha256=bit_info['bit_sha256'], accepted_frequency_mhz=100,
                  accepted_125mhz=False, github_pushed=False,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    write_json(out/'publication_result.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('root', 'repo', 'output', 'prior'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--timing', type=Path, nargs=3, required=True)
    parser.add_argument('--resume-worktree', action='store_true',
                        help='Recover only the declared publication overlay in a new output job')
    publish(parser.parse_args())
