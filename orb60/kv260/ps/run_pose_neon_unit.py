"""Actual A53 numerical unit execution; no SLAM/DPU throughput acceptance."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest


def run(build,output):
    build,output=Path(build).resolve(),Path(output).resolve()
    if platform.machine()!='aarch64':raise ValueError('Actual AArch64 board required')
    proof=json.loads((build/'CROSS_UNIT.json').read_text())
    if proof['status']!='CROSS_POSE_NEON_UNIT_COMPILED_NOT_EXECUTED':raise ValueError('Verified cross unit required')
    for group in ('source_sha256','binaries_sha256'):
        for name,h in proof[group].items():
            if Path(name).name!=name or digest(build/name)!=h:raise ValueError('Unit build input hash mismatch')
    if digest(Path(__file__).parent/'PoseQuadraticNeon.h')!=proof['source_sha256']['PoseQuadraticNeon.h']:
        raise ValueError('Numerical kernel differs from selected authored source')
    output.mkdir(parents=True,exist_ok=False)
    state=dict(status='RUNNING',scope='Actual A53 FP64 NEON equation unit only, no whole-system acceptance',
               native_machine=platform.machine(),cross_build_sha256=digest(build/'CROSS_UNIT.json'),
               header_sha256=proof['source_sha256']['PoseQuadraticNeon.h'],layouts={})
    try:
        for layout in ('col','row'):
            binary=build/('check_'+layout);cases=output/(layout+'_cases.f64')
            stdout=subprocess.check_output([str(binary),str(cases)],text=True,stderr=subprocess.STDOUT)
            value=json.loads(stdout)
            if value['status']!='QUADRATIC_EQUATIONS_PASS' or value['cases']!=20000 or value['max_normalized_error']>1e-12:
                raise ValueError('Actual NEON normal equations differ')
            state['layouts'][layout]=dict(result=value,binary_sha256=digest(binary),cases_sha256=digest(cases))
        state['status']='NATIVE_POSE_NEON_EQUATIONS_PASS'
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'NATIVE_UNIT.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True);return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
