"""Direct common-frame comparison. No alignment, scale fitting or interpolated poses."""
import argparse
from pathlib import Path
import cv2
import numpy as np
from common import rows,load,save,write_rows,pose_from_row,pose_error

def compare(reference,candidate,map_folder,output,diagnostic=False):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    baseline=rows(reference);actual=rows(candidate);seen=set();byid={}
    reference_byid={int(r['frame_index']):r for r in baseline}
    if len(reference_byid)!=len(baseline):raise ValueError('Duplicate reference frame index')
    for row in actual:
        if int(row['pose_valid']) not in (0,1):raise ValueError('pose_valid must be0 or1')
        key=int(row['frame_index'])
        if key in seen:raise ValueError('Duplicate candidate frame index')
        if key not in reference_byid:raise ValueError('Unknown candidate frame index')
        ref=reference_byid[key]
        if int(ref['timestamp_ns'])!=int(row['timestamp_ns']) or int(ref['map_id'])!=int(row['map_id']):
            raise ValueError('Timestamp/map mismatch at frame%d'%key)
        if 'source_frame_index' in row and int(ref['source_frame_index'])!=int(row['source_frame_index']):
            raise ValueError('Source frame mismatch')
        seen.add(key);byid[key]=row
    depth=load(Path(map_folder)/'map.json')['reference_median_depth'];errors=[];valid=0
    for ref in baseline:
        if not int(ref['pose_valid']):continue
        valid+=1;index=int(ref['frame_index']);other=byid.get(index)
        if other is None or not int(other['pose_valid']):continue
        if int(ref['timestamp_ns'])!=int(other['timestamp_ns']) or int(other['map_id'])!=int(ref['map_id']):
            raise ValueError('Timestamp/map mismatch at frame%d'%index)
        left,right=pose_from_row(ref),pose_from_row(other)
        if not np.isfinite(right).all() or not np.allclose(right[3],[0,0,0,1],atol=1e-6) or not np.allclose(right[:3,:3].T@right[:3,:3],np.eye(3),atol=1e-3) or abs(np.linalg.det(right[:3,:3])-1)>1e-3:
            raise ValueError('Invalid candidate rigid pose')
        translation,rotation=pose_error(left,right,depth)
        errors.append(dict(frame_index=index,timestamp_ns=ref['timestamp_ns'],position_error_relative=translation,
                           rotation_error_degrees=rotation))
    if not valid or not errors:raise ValueError('No valid common-frame poses')
    translation=np.array([r['position_error_relative'] for r in errors]);rotation=np.array([r['rotation_error_degrees'] for r in errors])
    fraction=len(errors)/valid
    passed=bool(np.percentile(translation,95)<=.02 and np.percentile(rotation,95)<=2 and fraction>=.95)
    report=dict(status='DIAGNOSTIC_ONLY' if diagnostic else ('PASS' if passed else 'FAIL'),
                reference_valid=valid,common_valid=len(errors),coverage=fraction,
                position_p95_relative=float(np.percentile(translation,95)),rotation_p95_degrees=float(np.percentile(rotation,95)),
                position_max_relative=float(translation.max()),rotation_max_degrees=float(rotation.max()),
                thresholds=dict(position_p95_relative=.02,rotation_p95_degrees=2,coverage_min=.95),
                alignment='none',scale_fitting='none',reference_median_depth=depth,
                claim='Regression reference, not physical ground truth')
    write_rows(output/'frame_errors.csv',errors);save(output/'comparison.json',report)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(14,4))
    for data,label in ((baseline,'reference'),(actual,'candidate')):
        positions=np.array([pose_from_row(r)[:3,3] if int(r['pose_valid']) else [np.nan]*3 for r in data])
        if len(positions):axes[0].plot(positions[:,0],positions[:,2],label=label,linewidth=1)
    axes[0].axis('equal');axes[0].legend();axes[0].set(xlabel='SLAM X',ylabel='SLAM Z',title='Same world coordinates, no alignment')
    indices=[r['frame_index'] for r in errors]
    axes[1].plot(indices,translation);axes[1].set(xlabel='frame',ylabel='position error / reference depth')
    axes[2].plot(indices,rotation);axes[2].set(xlabel='frame',ylabel='rotation error (degrees)')
    fig.tight_layout();fig.savefig(output/'trajectory_and_errors.png',dpi=150);plt.close(fig)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--map',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    result=compare(a.reference,a.candidate,a.map,a.output,a.diagnostic);print(result)
    if not a.diagnostic and result['status']!='PASS':raise SystemExit(1)
