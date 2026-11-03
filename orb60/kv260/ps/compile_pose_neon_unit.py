"""PC cross-build of the isolated FP64 NEON equation checker, not a board PASS."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest


def run(compiler,eigen,output):
    compiler,eigen,output=map(lambda p:Path(p).resolve(),(compiler,eigen,output))
    if platform.machine()!='x86_64' or subprocess.check_output([str(compiler),'-dumpmachine'],text=True).strip()!='aarch64-none-linux-gnu':
        raise ValueError('Explicit PC to AArch64 cross toolchain required')
    output.mkdir(parents=True,exist_ok=False);authored=Path(__file__).parent
    header=authored/'PoseQuadraticNeon.h';(output/header.name).write_bytes(header.read_bytes())
    original=(authored/'check_pose_quadratic.cc').read_text();anchor='#include "PoseQuadratic.h"'
    if original.count(anchor)!=1:raise ValueError('Equation unit include boundary mismatch')
    private=original.replace(anchor,'#include "PoseQuadraticNeon.h"')
    alias='using A=Eigen::Matrix<double,2,6>;'
    if private.count(alias)!=1:raise ValueError('Jacobian layout alias mismatch')
    (output/'check_col.cc').write_text(private)
    (output/'check_row.cc').write_text(private.replace(alias,'using A=Eigen::Matrix<double,2,6,Eigen::RowMajor>;'))
    commands=[[str(compiler),'-O2','-std=c++14','-ffp-contract=off','-mcpu=cortex-a53','-I'+str(eigen),str(output/('check_'+layout+'.cc')),'-o',str(output/('check_'+layout))] for layout in ('col','row')]
    state=dict(status='RUNNING',scope='PC cross unit executable only; actual A53 and independent NumPy gates remain required',
               compiler_sha256=digest(compiler),commands=commands,source_sha256={p.name:digest(p) for p in output.iterdir() if p.is_file()})
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        binaries=[output/('check_'+layout) for layout in ('col','row')]
        abi=subprocess.check_output(['file',*[str(p) for p in binaries]],text=True)
        if abi.count('ARM aarch64')!=2:raise ValueError('Wrong numeric unit architecture')
        state.update(status='CROSS_POSE_NEON_UNIT_COMPILED_NOT_EXECUTED',architecture=abi,binaries_sha256={p.name:digest(p) for p in binaries})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'CROSS_UNIT.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('compiler','eigen','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
