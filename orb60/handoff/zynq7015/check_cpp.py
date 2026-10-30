"""Compare independent C++ OpenCV fixed-inlier results with frozen Python solves."""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np
from common import load,save,pose_error

def check(bundle,program,output):
    bundle=bundle.resolve();program=program.resolve()
    folder=bundle/'localization_reference/pnp_cases';depth=load(bundle/'map/map.json')['reference_median_depth'];results=[]
    for item in load(folder/'index.json'):
        name=item['name'];case=load(folder/(name+'.json'))
        raw=subprocess.check_output([str(program),str(folder/(name+'.json')),str(folder/(name+'.csv'))],text=True)
        result=json.loads(raw);position,rotation=pose_error(np.array(case['twc']),np.array(result['twc']),depth)
        results.append(dict(case=name,frame_index=item['frame_index'],opencv_cpp=result['opencv'],
                            position_error_relative=position,rotation_error_degrees=rotation,
                            passed=position<=.001 and rotation<=.1))
    passed=len(results)==20 and all(r['passed'] for r in results)
    report=dict(status='PASS' if passed else 'FAIL',cases=results,maximum_position_error_relative=max(r['position_error_relative'] for r in results),
                maximum_rotation_error_degrees=max(r['rotation_error_degrees'] for r in results),
                thresholds=dict(position_relative=.001,rotation_degrees=.1),
                scope='Independent C++ OpenCV fixed correspondences/inliers and same initial pose; not Zynq PS application acceptance')
    save(output,report);print(report['status'],len(results),'cases',report['maximum_position_error_relative'],report['maximum_rotation_error_degrees'])
    if not passed:raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--program',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();check(a.bundle,a.program,a.output)
