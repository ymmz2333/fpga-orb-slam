"""Read-only prepared-frame distortion preview; no SLAM runs or video re-encoding."""
import argparse,csv,hashlib,json,pathlib,shutil
import cv2,numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--datasets',type=pathlib.Path,default=ROOT/'runtime/c/datasets/TT_C1_01')
    p.add_argument('--yaml',type=pathlib.Path,default=ROOT/'configs/c/tello_oafd_960x720_provisional.yaml')
    p.add_argument('--output',type=pathlib.Path,default=ROOT/'runtime/c/visual_checks/provisional_intrinsics')
    a=p.parse_args(); corpus=a.datasets.resolve(); output=a.output.resolve()
    if output==corpus or corpus in output.parents: raise ValueError('Output cannot be inside the input corpus')
    f=cv2.FileStorage(str(a.yaml),cv2.FILE_STORAGE_READ)
    if not f.isOpened(): raise ValueError('Cannot open YAML')
    val=lambda key:f.getNode(key).real()
    width,height=int(val('Camera.width')),int(val('Camera.height'))
    K=np.array([[val('Camera1.fx'),0,val('Camera1.cx')],[0,val('Camera1.fy'),val('Camera1.cy')],[0,0,1]],np.float64)
    D=np.array([val('Camera1.'+s) for s in ('k1','k2','p1','p2')],np.float64)
    if not f.getNode('Camera1.k3').empty(): D=np.append(D,val('Camera1.k3'))
    f.release()
    if width<1 or height<1 or not np.isfinite(K).all() or not np.isfinite(D).all(): raise ValueError('Invalid camera model')
    mapx,mapy=cv2.initUndistortRectifyMap(K,D,None,K,(width,height),cv2.CV_32FC1)
    u,v=np.meshgrid(np.arange(width,dtype=np.float64),np.arange(height,dtype=np.float64))
    x,y=(u-K[0,2])/K[0,0],(v-K[1,2])/K[1,1]; r=x*x+y*y
    radial=1+D[0]*r+D[1]*r*r+(D[4] if len(D)>4 else 0)*r*r*r
    expected_x=K[0,0]*(x*radial+2*D[2]*x*y+D[3]*(r+2*x*x))+K[0,2]
    expected_y=K[1,1]*(y*radial+D[2]*(r+2*y*y)+2*D[3]*x*y)+K[1,2]
    error=float(max(np.max(np.abs(expected_x-mapx)),np.max(np.abs(expected_y-mapy))))
    if error>1e-3: raise ValueError('OpenCV map disagrees with independent Brown-Conrady formula')
    shift=np.hypot(mapx-u,mapy-v)
    metrics=dict(mean_px=float(shift.mean()),p95_px=float(np.percentile(shift,95)),max_px=float(shift.max()),
        source_center_outside_percent=float(np.mean((mapx<0)|(mapx>width-1)|(mapy<0)|(mapy>height-1))*100),
        definition='Corrected output pixel to original source sampling position, same K, no crop; not calibration error')
    output.mkdir(parents=True,exist_ok=True); assets=output/'assets'; assets.mkdir(exist_ok=True)
    heat=cv2.applyColorMap(np.uint8(np.rint(shift/shift.max()*255)) if shift.max()>0 else np.zeros(shift.shape,np.uint8),cv2.COLORMAP_TURBO)
    cv2.imwrite(str(assets/'displacement.png'),heat)
    zero_x,zero_y=cv2.initUndistortRectifyMap(K,np.zeros_like(D),None,K,(width,height),cv2.CV_32FC1)
    clips=json.loads((corpus/'manifest.json').read_text(encoding='utf-8'))['clips']; samples=[]
    for clip in clips:
        dataset=corpus/clip['dataset']
        with (dataset/'frames.csv').open(encoding='utf-8',newline='') as stream: rows=list(csv.DictReader(stream))
        for fraction in (.2,.5,.8):
            row=rows[round((len(rows)-1)*fraction)]; source=dataset/row['image']; original_bytes=source.read_bytes()
            if hashlib.sha256(original_bytes).hexdigest()!=row['sha256']: raise ValueError('Prepared input checksum mismatch')
            image=cv2.imdecode(np.frombuffer(original_bytes,np.uint8),cv2.IMREAD_GRAYSCALE)
            if image is None or image.shape!=(height,width): raise ValueError('Frame resolution mismatch')
            if not np.array_equal(image,cv2.remap(image,zero_x,zero_y,cv2.INTER_LINEAR)):
                raise ValueError('Zero-distortion identity check failed')
            corrected=cv2.remap(image,mapx,mapy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
            stem='frame_%02d'%len(samples); raw=stem+'_original.png'; target=stem+'_corrected.png'
            (assets/raw).write_bytes(original_bytes); cv2.imwrite(str(assets/target),corrected)
            if hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']: raise ValueError('Source changed during preview generation')
            samples.append(dict(clip=clip['clip'],frame_index=int(row['frame_index']),
                time_s=(int(row['timestamp_ns'])-1000000000)/1e9,corrupt=row['corrupt'],
                original='assets/'+raw,corrected='assets/'+target,sha256=row['sha256']))
    data=dict(generator='build_intrinsics_preview.py',width=width,height=height,K=K.tolist(),D=D.tolist(),metrics=metrics,
        label='临时内参，待标定后重跑',samples=samples,opencv_version=cv2.__version__,
        checks=dict(analytic_map_max_error_px=error,zero_distortion_identity=True,source_sha256_unchanged=True),
        yaml_sha256=hashlib.sha256(a.yaml.read_bytes()).hexdigest())
    text=(ROOT/'tools/intrinsics_preview.html').read_text(encoding='utf-8')
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
    (output/'index.html').write_text(text.replace('__PREVIEW_DATA__',payload),encoding='utf-8',newline='\n')
    (output/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    # One static pair is available even without a browser.
    first=samples[0]; left=cv2.imread(str(output/first['original'])); right=cv2.imread(str(output/first['corrected']))
    pair=np.concatenate([left,right],axis=1); pair=cv2.copyMakeBorder(pair,45,0,0,0,cv2.BORDER_CONSTANT)
    cv2.putText(pair,'ORIGINAL',(15,30),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
    cv2.putText(pair,'CORRECTED: SAME K, NO CROP',(width+15,30),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
    cv2.imwrite(str(output/'comparison.png'),pair)
    print('INTRINSICS_PREVIEW_READY '+json.dumps(dict(output=str(output),samples=len(samples),metrics=metrics,checks=data['checks']),ensure_ascii=False))

if __name__=='__main__': main()
