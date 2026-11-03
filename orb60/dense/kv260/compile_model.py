"""Target compilation and fail-closed placement inspection in Vitis AI 2.5."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import hashlib
import re
from .common import digest,save
from .placement import inspect_xmodel
from .preflight import fingerprints


def check_application_acceptance(gate,selection):
    if selection.get('user_visual_acceptance') is not True:raise ValueError('Explicit user visual acceptance required')
    if gate.get('status')!='QUANTIZATION_FAILED' or gate.get('reproduction_status')!='PASS':raise ValueError('Preserved numeric failure and exact selected-output reproduction required')
    if not gate.get('checkpoint_sha256') or gate['checkpoint_sha256']!=selection.get('weights_sha256'):raise ValueError('Application acceptance belongs to another checkpoint')


def main():
    p=argparse.ArgumentParser()
    for key in ['model','arch','output']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--quantization-report',type=Path,required=True)
    p.add_argument('--diagnostic-only',action='store_true')
    p.add_argument('--application-acceptance',type=Path,help='Explicit visual acceptance of an exactly reproduced QAT checkpoint; numeric failure is preserved')
    p.add_argument('--ps-operator-policy',type=Path,help='Model-bound, explicitly reviewed auxiliary PS operators')
    p.add_argument('--family',choices=['midas','fastdepth'],default='midas')
    p.add_argument('--inspect-existing',action='store_true',help='Recheck an existing compiler exit=0 artifact; never infer success from an old file')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    report={'status':'COMPILATION_STARTED','hardware_inference_verified':False}
    try:
        gate=json.loads(a.quantization_report.read_text())
        application=False
        if a.application_acceptance:
            check_application_acceptance(gate,json.loads(a.application_acceptance.read_text()));application=True
        if gate.get('status')!='QUANTIZATION_PASS' and not application and not (a.diagnostic_only and gate.get('status')=='QUANTIZATION_FAILED'):
            raise ValueError('Passing real INT8 gate required for deployment; failed gate may be compiled only as explicit diagnostics')
        if gate.get('artifacts',{}).get(a.model.name)!=digest(a.model):raise ValueError('Target source is not the gated quantizer artifact')
        arch=a.output/'arch.json';shutil.copyfile(a.arch,arch)
        profile=json.loads(Path(__file__).with_name('profile.json').read_text());profile.update(arch_sha256=digest(arch),fingerprints=sorted(fingerprints(json.loads(arch.read_text()))))
        save(a.output/'target_profile.json',profile)
        model_name=a.family+'_kv260_b4096'
        command=['vai_c_xir','-x',str(a.model),'-a',str(arch),'-o',str(a.output),'-n',model_name]
        report.update(command=command,source_model_sha256=digest(a.model),arch_sha256=digest(arch),quantization_report_sha256=digest(a.quantization_report))
        if a.inspect_existing:
            prior=json.loads((a.output/'compilation.json').read_text())
            if prior.get('compiler_exit_code')!=0 or prior.get('source_model_sha256')!=digest(a.model) or prior.get('arch_sha256')!=digest(arch):
                raise ValueError('Existing compiler record/input mismatch')
            model=a.output/(model_name+'.xmodel')
            expected=re.findall(r'\b[0-9a-f]{32}\b',(a.output/'md5sum.txt').read_text())
            if not expected or hashlib.md5(model.read_bytes()).hexdigest() not in expected:raise ValueError('Existing compiled artifact differs from compiler checksum')
            report.update(compiler_exit_code=0,compiler_reused=True)
        else:
            with (a.output/'compiler.log').open('w') as log:
                done=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            report['compiler_exit_code']=done.returncode
            if done.returncode:raise RuntimeError('Compiler failed; see compiler.log')
        model=a.output/(model_name+'.xmodel')
        policy=json.loads(a.ps_operator_policy.read_text()) if a.ps_operator_policy else None
        inspect_xmodel(model,a.output/'placement.json',source=a.model,family=a.family,ps_policy=policy)
        placed=json.loads((a.output/'placement.json').read_text())
        if profile['fingerprints']:
            if not set(placed['fingerprints']).issubset(profile['fingerprints']):raise ValueError('Model/arch fingerprint mismatch')
        else:
            # VAI 2.5's official arch.json names a target instead of spelling out its fingerprint.
            target=json.loads(arch.read_text()).get('target')
            if not target or placed.get('target_names')!=[target]:raise ValueError('Compiled DPU name does not match named arch target')
            profile.update(fingerprints=placed['fingerprints'],fingerprint_source='compiled named-target XIR graph')
            save(a.output/'target_profile.json',profile)
        status='APPLICATION_ACCEPTED_TARGET_COMPILE_BOARD_UNTESTED' if application else ('DIAGNOSTIC_ONLY_NOT_ACCEPTED' if a.diagnostic_only else 'TARGET_COMPILE_PASS_BOARD_UNTESTED')
        report.update(status=status,model_sha256=digest(model),family=a.family,model_file=model.name,numerical_acceptance=gate.get('status'),user_visual_acceptance=application)
    except Exception as e:
        report.update(status='FAILED',error=repr(e));save(a.output/'compilation.json',report);raise
    save(a.output/'compilation.json',report)

if __name__=='__main__':main()
