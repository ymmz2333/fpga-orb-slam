"""Native full packed-file gray/RGB gate, independent from SLAM/DPU execution."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from ..packed_yuv import validate
from ..native_products import verify,check_unchanged,digest


def validate_native(proof,source,executable):
    p=json.loads(Path(proof).read_text())
    if p.get('status')!='NATIVE_PACKED_YUV_PIXEL_PASS' or p.get('source_proof_sha256')!=digest(source) or p.get('executable_sha256')!=digest(executable) or p.get('frames')!=2297:
        raise ValueError('Full native packed-source pixel proof required')
    for path,h in p['opencv_sha256'].items():
        if digest(path)!=h:raise ValueError('Native packed color conversion library changed')
    return p


def run(native_build,packed_proof,raw,identities,color_identities,reference,lut,executable,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    source=validate(packed_proof,raw,identities,color_identities,reference,lut)
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENCV_FOR_THREADS_NUM':'1','ORB60_PACKED_GRAY_LUT':str(Path(lut).resolve()),'ORB60_PACKED_VERIFY_COLOR_CSV':str(Path(color_identities).resolve())}
    products=verify(native_build,executable,env)
    if products['build_status'] not in ('NATIVE_PACKED_YUV_COMPONENT_PASS','NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS'):raise ValueError('Wrong native packed input build')
    linked=subprocess.check_output(['ldd',str(executable)],env=env,text=True)
    libraries={}
    for line in linked.splitlines():
        if 'libopencv_' in line and '=>' in line:
            p=Path(line.split('=>',1)[1].strip().split(' (',1)[0]).resolve();libraries[str(p)]=digest(p)
    if not any('libopencv_imgproc' in p for p in libraries):raise ValueError('Packed color converter not resolved')
    state=dict(status='RUNNING',scope='Full native packed file parsing, original gray CRC and independent OpenCV RGB CRC checked for every frame; no PL/DPU or live-camera FPS claim',
               source_proof_sha256=digest(packed_proof),format=source['format'],frames=source['frames'],executable_sha256=digest(executable),opencv_sha256=libraries,native_products=products)
    try:
        command=[str(executable),'--verify-video',source['format'].lower()+':'+str(Path(raw).resolve()),str(Path(identities).resolve())]
        child=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=600)
        (output/'native.log').write_text(child.stdout)
        if child.returncode or 'NATIVE_VIDEO_IDENTITY_PASS frames=2297' not in child.stdout:raise ValueError('Native packed full pixel comparison failed: '+child.stdout[-1000:])
        check_unchanged(products)
        if any(digest(p)!=h for p,h in libraries.items()):raise ValueError('Native converter changed during gate')
        state['status']='NATIVE_PACKED_YUV_PIXEL_PASS'
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'PROOF.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],format=source['format'],frames=source['frames'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('native_build','packed_proof','raw','identities','color_identities','reference','lut','executable','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
