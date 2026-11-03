"""Full native emulated-sensor stream pixel gate; no SLAM/DPU execution."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from ..packed_stream import validate_contract,load,digest
from ..native_products import verify,check_unchanged


def validate_native(proof,source,stream_proof,executable):
    p=load(proof)
    if p.get('status')!='NATIVE_PACKED_SENSOR_STREAM_PIXEL_PASS' or p.get('source_proof_sha256')!=digest(source) or p.get('stream_proof_sha256')!=digest(stream_proof) or p.get('executable_sha256')!=digest(executable) or p.get('frames')!=2297:
        raise ValueError('Full native sensor-stream pixel proof required')
    for path,h in p['opencv_sha256'].items():
        if digest(path)!=h:raise ValueError('Native sensor color conversion library changed')
    return p


def run(native_build,source,stream_proof,headers,identities,colors,reference,lut,executable,address,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    p,s=validate_contract(stream_proof,source,headers,identities,colors,reference,lut)
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENCV_FOR_THREADS_NUM':'1','ORB60_PACKED_GRAY_LUT':str(Path(lut).resolve()),
         'ORB60_PACKED_VERIFY_COLOR_CSV':str(Path(colors).resolve()),'ORB60_PACKED_HEADERS':str(Path(headers).resolve()),
         'ORB60_PACKED_STREAM_SHA256':p['data_sha256'],'ORB60_PACKED_STREAM_STATUS':str(output.resolve()/'source_trace.json')}
    products=verify(native_build,executable,env)
    if products['build_status'] not in ('NATIVE_PACKED_STREAM_COMPONENT_PASS','NATIVE_PACKED_ARM_CRC_COMPONENT_PASS','NATIVE_PACKED_BMP_COMPONENT_PASS','NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS','NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS','NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS','NATIVE_TRACKING_TRACE_BUILD_PASS','NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS'):raise ValueError('Wrong native stream build')
    linked=subprocess.check_output(['ldd',str(executable)],env=env,text=True);libraries={}
    for line in linked.splitlines():
        if 'libopencv_' in line and '=>' in line:
            f=Path(line.split('=>',1)[1].strip().split(' (',1)[0]).resolve();libraries[str(f)]=digest(f)
    if not any('libopencv_imgproc' in n for n in libraries):raise ValueError('Native stream color converter not resolved')
    state=dict(status='RUNNING',scope='Every original gray and packed RGB frame verified through native LAN byte input. PC emulates sensor only; no system/DPU/FPS or final standalone claim',
               source_proof_sha256=digest(source),stream_proof_sha256=digest(stream_proof),headers_sha256=digest(headers),
               executable_sha256=digest(executable),opencv_sha256=libraries,frames=s['frames'],native_products=products)
    (output/'PROOF.json').write_text(json.dumps(state,indent=2)+'\n')
    try:
        with (output/'native.log').open('w') as log:
            cmd=[str(executable),'--verify-video',s['format'].lower()+':listen:'+address,str(Path(identities).resolve())]
            child=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
        text=(output/'native.log').read_text()
        if child.returncode or 'NATIVE_VIDEO_IDENTITY_PASS frames=2297' not in text:raise ValueError('Native stream full pixel gate failed: '+text[-1500:])
        trace=load(output/'source_trace.json')
        if trace.get('status')!='DRAINED' or trace.get('headers_verified')!=s['frames'] or trace.get('master_sha256')!=p['data_sha256']:raise ValueError('Sealed native source did not fully drain')
        check_unchanged(products)
        if any(digest(f)!=h for f,h in libraries.items()):raise ValueError('Native converter changed during gate')
        state.update(status='NATIVE_PACKED_SENSOR_STREAM_PIXEL_PASS',source_trace=trace)
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'PROOF.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],frames=s['frames'])),flush=True)


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for k in ('native_build','source','stream_proof','headers','identities','colors','reference','lut','executable','output'):a.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    a.add_argument('--address',required=True);run(**vars(a.parse_args()))
