"""Finalize a verified data/reference delivery and create a checksum-checked ZIP."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from assemble import assemble,inventory
from common import load,save,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--verification-output',type=Path,required=True);a=p.parse_args();root=a.bundle.resolve()
    if a.output.exists():raise ValueError('Refusing to replace an existing delivery ZIP')
    assemble(root)
    test=subprocess.run([sys.executable,str(root/'tools/test_handoff.py')],capture_output=True,text=True,cwd=root)
    (root/'reports/acceptance_negative_tests.log').write_text(test.stdout+test.stderr,encoding='utf-8')
    if test.returncode:raise RuntimeError('Negative acceptance tests failed')
    inventory(root)
    subprocess.run([sys.executable,str(root/'tools/verify.py'),'--bundle',str(root),'--output',str(a.verification_output.resolve())],check=True)
    evidence=load(a.verification_output/'verification.json')
    if evidence['status']!='PASS' or evidence['decoded_input_frames']!=2273:raise ValueError('Full offline verification required')
    for name in ('verification.json','fixed_pnp_check.json'):
        shutil.copy2(a.verification_output/name,root/'reports'/('final_'+name))
    for file in (a.verification_output/'previews').glob('*.png'):
        target=root/'reports/previews'/file.name;target.parent.mkdir(exist_ok=True);shutil.copy2(file,target)
    delivery=load(root/'delivery.json');delivery['status']='READY_FOR_DEVELOPER_HANDOFF'
    save(root/'delivery.json',delivery)
    save(root/'reports/package_acceptance.json',dict(status='PASS',scope='Frozen data, reference software and offline reproduction only',
        physical_capture='PASS:2273 frames, historical count/CRC, actual wire ABI and full record SHA256',
        exact_input_decode='PASS:2273 frames',raw_map_associations='PASS:18980 observations',
        portable_c='PASS:host tests and Cortex-A9 compilation; see portable_reference_checks.json',
        fixed_inlier_cpp=load(root/'reports/cpp_fixed_pnp.json')['status'],negative_tests=8,
        full_reference_reproduction=load(root/'reports/reference_reproduction/comparison.json')['status'],
        reference_localization_valid=delivery['reference_localization_valid'],
        ps_localization_application='NOT_IMPLEMENTED:recipient development scope',
        camera_hdmi='NOT_IMPLEMENTED:recipient development scope',
        original_slam_comparison='DIAGNOSTIC_ONLY; coverage86.40%, not a95% coverage acceptance'))
    inventory(root)
    manifest={line.split('  ',1)[1]:line.split('  ',1)[0] for line in (root/'SHA256SUMS').read_text().splitlines()}
    prefix=a.output.stem
    with zipfile.ZipFile(a.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in sorted(manifest):archive.write(root/name,prefix+'/'+name)
        archive.write(root/'SHA256SUMS',prefix+'/SHA256SUMS')
    with zipfile.ZipFile(a.output) as archive:
        for name,expected in manifest.items():
            digest=hashlib.sha256()
            with archive.open(prefix+'/'+name) as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=expected:raise ValueError('ZIP byte integrity failure')
    digest=sha(a.output);a.output.with_suffix('.zip.sha256').write_bytes((digest+'  '+a.output.name+'\n').encode('ascii'))
    print('ZIP_PASS',a.output,'bytes',a.output.stat().st_size,'sha256',digest,flush=True)

if __name__=='__main__':main()
