"""Independent NumPy confirmation of both actually executed A53 layouts."""
import argparse
import json
from pathlib import Path
from .build_network_adapter import digest
from .check_pose_quadratic import check


def run(folder,output):
    folder,output=Path(folder).resolve(),Path(output).resolve()
    native=json.loads((folder/'NATIVE_UNIT.json').read_text())
    if native['status']!='NATIVE_POSE_NEON_EQUATIONS_PASS' or native['native_machine']!='aarch64':raise ValueError('Actual A53 unit required')
    header=Path(__file__).parent/'PoseQuadraticNeon.h'
    if digest(header)!=native['header_sha256']:raise ValueError('Native numerical kernel differs')
    result=dict(status='RUNNING',scope='Independent equation validation only; full native link and SLAM gates remain required',
                native_machine='aarch64',header_sha256=digest(header),native_proof_sha256=digest(folder/'NATIVE_UNIT.json'),layouts={})
    for layout in ('col','row'):
        evidence=native['layouts'][layout];cases=folder/(layout+'_cases.f64');value=evidence['result']
        if digest(cases)!=evidence['cases_sha256'] or value['status']!='QUADRATIC_EQUATIONS_PASS' or value['cases']!=20000 or value['max_normalized_error']>1e-12:
            raise ValueError('Native numerical evidence differs')
        result['layouts'][layout]=check(cases,folder/('NUMPY_'+layout+'.json'),layout)
    result['status']='INDEPENDENT_NATIVE_NEON_QUADRATIC_PASS'
    output.write_text(json.dumps(result,indent=2)+'\n');print(result['status']);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.folder,a.output)
