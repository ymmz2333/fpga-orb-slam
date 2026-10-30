"""Assemble a self-contained offline review delivery, clearly excluding unbuilt ARM/RK claims."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'orb60/build/demo_bridge'


def main():
    verification=json.loads((BUILD/'verification.json').read_text())
    if verification['status']!='PASS_OFFLINE_SOFTWARE':raise ValueError('Passing offline gate required')
    # Never package changed code under an older passing report.
    for name,digest in verification['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Verified source changed: '+name)
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    stage=BUILD/('delivery_'+stamp);stage.mkdir()
    def tree(src,dst):
        shutil.copytree(src,stage/dst,ignore=shutil.ignore_patterns('build','output','test-results','__pycache__','*.pyc','.git'),dirs_exist_ok=False)
    tree(ROOT/'zynq7015_demo','zynq7015_demo')
    tree(ROOT/'orb60/demo_bridge','orb60/demo_bridge')
    tree(ROOT/'orb60/viewer','orb60/viewer')
    (stage/'scripts').mkdir()
    for name in ('project_env.ps1','local_env.example.ps1'):
        shutil.copy2(ROOT/'scripts'/name,stage/'scripts'/name)
    native=stage/'orb60/build/demo_bridge/native';native.mkdir(parents=True)
    for name in ('zynq-demo.exe','test-zslam.exe','test-bridge.exe','checks.json'):
        shutil.copy2(BUILD/'native'/name,native/name)
    shutil.copytree(BUILD/'native/test-fixtures',native/'test-fixtures')
    reports=stage/'reports';reports.mkdir()
    for pattern in ('*.json','*.log','*.png'):
        for source in BUILD.glob(pattern):
            if source.name not in ('delivery.json','unpacked_verification.json'):
                shutil.copy2(source,reports/source.name)
    shutil.copy2(BUILD/'arm/checks.json',reports/'arm_build.json')
    hardware=stage/'hardware';hardware.mkdir()
    frozen=ROOT/'zynq7015_usb_slam_20261024/artifacts/fpga'
    shutil.copytree(frozen/'export',hardware/'export')
    shutil.copytree(frozen/'firmware',hardware/'firmware')
    shutil.copytree(frozen/'route',hardware/'retained_route')
    release=stage/'zynq_release';(release/'bin').mkdir(parents=True);(release/'config').mkdir()
    shutil.copy2(ROOT/'zynq7015_usb_slam_20261024/artifacts/camera_runtime/s1-controls/s1-reset-bridge',release/'bin/s1-reset-bridge')
    for name in ('camera_source.csv','camera_orb.csv'):shutil.copy2(ROOT/'orb60/demo_bridge/config'/name,release/'config'/name)
    shutil.copy2(ROOT/'orb60/demo_bridge/run_zynq.sh',release/'run_zynq.sh')
    (release/'BUILD_REQUIRED.txt').write_text('New zynq-demo ARM ELF is NOT built. Configure GCC7.3.1, run build_arm.py and place the verified ELF in bin/zynq-demo. Do not run the Windows .exe on Zynq.\n')
    readme='''# 两阶段演示桥接：本机软件验证交付

先阅读 orb60/demo_bridge/README_ZH.md。

- 摄像头固定在Zynq，RK异构建图后交接地图，再由Zynq独立定位。
- 本包包含新增源码、原生Windows验证程序、3帧历史实测传输样本、原配套ORB150MHz/HDMI bitstream和历史路由报告。
- 本包没有新ARM ELF，也没有RK新程序；它们尚未完成目标编译。zynq-demo.exe仅用于Windows软件验证。
- 没有此次实机建图/断网定位/SD重启/FPS或轨迹精度验收；协议测试中的相机和有效位姿为明确标注的合成夹具。
- zynq_release是待补ARM ELF的部署模板，不能直接声称为可启动SD镜像。不覆盖BOOT.BIN、内核或旧发布版。

用本机已有Python环境在解压目录运行：

    <Python3.12路径> -m orb60.demo_bridge.verify

需要numpy、PySide6等requirements依赖。预编译原生程序仅适用于Win64。
SHA256SUMS覆盖全部交付文件；reports中记录本次验证，hardware/retained_route是原有PL报告，未重新布局布线。
'''
    (stage/'README_FIRST_ZH.md').write_text(readme,encoding='utf-8')
    files=sorted(p for p in stage.rglob('*') if p.is_file())
    checks=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(stage).as_posix()+'\n' for p in files)
    (stage/'SHA256SUMS').write_bytes(checks.encode('utf-8'))
    output=BUILD/('orb_two_stage_offline_'+stamp+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(stage).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise ValueError('ZIP CRC failed')
    receipt=dict(zip=str(output),stage=str(stage),files=len(files)+1,size=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                 status='OFFLINE_SOFTWARE_DELIVERY',board_acceptance='NOT_RUN',new_arm_elf_included=False,new_rk_binary_included=False,
                 retained_bitstream_sha256=hashlib.sha256((hardware/'export/s_wrapper.bit').read_bytes()).hexdigest())
    (BUILD/'delivery.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
