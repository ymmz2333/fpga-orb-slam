"""PC-only checkerboard calibration for bounded capture-only PGM recordings.

Uses the same five-coefficient pinhole model as the PS application. Never emits
a calibration CSV when coverage, pose diversity or reprojection checks fail.
OpenCV reference: https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html
"""
from pathlib import Path
import argparse,csv,hashlib,json,math,os,re,sys
ROOT=Path(__file__).resolve().parents[1]
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'

class Rejected(RuntimeError):
    def __init__(self,reason,report=None):super().__init__(reason);self.report=report or {}

def checkerboard_pattern(pattern):
    if len(pattern)!=2 or any(type(v) is not int or not 3<=v<=32 for v in pattern) or pattern[0]*pattern[1]>512:
        raise Rejected('Checkerboard needs3..32 inner corners per axis and at most512 total')
    return tuple(pattern)

def vision():
    folder=ROOT/'build/calibration_python'
    if folder.is_dir():sys.path.insert(0,str(folder))
    try:import cv2,numpy as np
    except ImportError as e:raise RuntimeError('PC calibration needs NumPy and OpenCV; run tools/fetch_calibration_opencv.py with the bundled Python (not the ARM runtime)') from e
    if cv2.__version__!='4.13.0':raise RuntimeError('PC calibration requires pinned OpenCV4.13.0')
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    return cv2,np

def crop_geometry(meta):
    keys=['source_width','source_height','crop_x','crop_y','output_width','output_height']
    if any(type(meta.get(k)) is not int for k in keys) or meta.get('resized') is not False:raise Rejected('Missing explicit unscaled camera geometry')
    w,h=meta['source_width'],meta['source_height']
    if (w,h) not in [(960,720),(1280,720),(1280,800),(1024,768)]:raise Rejected('Unsupported source geometry')
    if (meta['output_width'],meta['output_height'],meta['crop_x'],meta['crop_y'])!=(960,720,(w-960)//2,(h-720)//2):raise Rejected('Capture crop differs from the paired ORB contract')
    return w,h,meta['crop_x'],meta['crop_y']

def source_values(matrix,distortion,meta):
    w,h,x,y=crop_geometry(meta)
    values=[float(matrix[0,0]),float(matrix[1,1]),float(matrix[0,2]+x),float(matrix[1,2]+y)]+[float(v) for v in distortion.reshape(-1)]
    if len(values)!=9 or not all(math.isfinite(v) for v in values):raise Rejected('Non-finite or non-five-coefficient calibration')
    if not(values[0]>0 and values[1]>0 and 0<values[2]<w and 0<values[3]<h):raise Rejected('Camera focal length/principal point outside physical image bounds')
    return [w,h,*values]

def detect_checkerboard(image,pattern):
    """Search complete boards in original pixels; tile offsets are translations."""
    cv,np=vision();pattern=checkerboard_pattern(pattern)
    if image.shape!=(720,960) or image.dtype!=np.uint8:raise Rejected('Checkerboard detector needs the original960x720 grayscale image')
    def refine(corners,method,roi,algorithm='SB'):
        grid=corners.reshape(pattern[1],pattern[0],2)
        pitch=min(float(np.median(np.linalg.norm(np.diff(grid,axis=0),axis=2))),float(np.median(np.linalg.norm(np.diff(grid,axis=1),axis=2))))
        radius=max(2,min(5,int(pitch*.35)))
        refined=cv.cornerSubPix(image,corners.copy(),(radius,radius),(-1,-1),(cv.TERM_CRITERIA_EPS|cv.TERM_CRITERIA_COUNT,100,.001))
        shift=float(np.max(np.linalg.norm(refined-corners,axis=2)))
        if not np.isfinite(refined).all() or shift>pitch*.35:return None
        return refined,dict(method=method,algorithm=algorithm,roi=roi,refinement='original_full_image_subpixel',refinement_radius=radius,max_refinement_shift_pixels=shift)
    found,corners=cv.findChessboardCornersSB(image,pattern,flags=cv.CALIB_CB_NORMALIZE_IMAGE)
    if found:
        result=refine(corners,'full_original_pixels',[0,0,960,720])
        if result is not None:return result
    # A small physical target can be missed among desk/monitor texture. Fixed
    # overlapping windows reduce clutter without rescaling or warping pixels.
    # EXHAUSTIVE/ACCURACY increases search effort, not fit/coverage tolerance.
    flags=cv.CALIB_CB_NORMALIZE_IMAGE|cv.CALIB_CB_EXHAUSTIVE|cv.CALIB_CB_ACCURACY
    for y in [0,180,360]:
        for x in [0,240,480]:
            found,corners=cv.findChessboardCornersSB(image[y:y+360,x:x+480],pattern,flags=flags)
            if found:
                corners=corners.copy();corners[:,:,0]+=x;corners[:,:,1]+=y
                # SB's estimates at a tile boundary can depend on context.
                # Refine all observations against the same full original image
                # and reject jumps approaching a different checkerboard corner.
                result=refine(corners,'overlapping_original_pixel_tile',[x,y,480,360])
                if result is not None:return result
    # The classic complete-grid detector complements SB for this small target.
    # It uses exactly the same source coordinates, subpixel refinement and fit
    # quality gates; no inferred/missing checkerboard corners are fabricated.
    for x,y,w,h in [(0,0,960,720)]+[(x,y,480,360) for y in [0,180,360] for x in [0,240,480]]:
        found,corners=cv.findChessboardCorners(image[y:y+h,x:x+w],pattern,flags=cv.CALIB_CB_ADAPTIVE_THRESH|cv.CALIB_CB_NORMALIZE_IMAGE)
        if found:
            corners=corners.copy();corners[:,:,0]+=x;corners[:,:,1]+=y
            result=refine(corners,'classic_original_pixel_grid',[x,y,w,h],'classic')
            if result is not None:return result
    return None,dict(method='no_complete_checkerboard')

def fit_observations(object_points,image_points,meta,pattern=(9,6)):
    cv,np=vision();crop_geometry(meta);columns,rows=checkerboard_pattern(pattern);count=columns*rows
    if len(image_points)<15 or len(image_points)>60 or len(object_points)!=len(image_points):raise Rejected('Need15..60 usable checkerboard views')
    for objects,pixels in zip(object_points,image_points):
        if objects.shape!=(count,3) or pixels.shape!=(count,1,2) or not np.isfinite(objects).all() or not np.isfinite(pixels).all():raise Rejected('Checkerboard observation shape or numeric value invalid')
        if np.any(pixels[:,:,0]<0) or np.any(pixels[:,:,0]>=960) or np.any(pixels[:,:,1]<0) or np.any(pixels[:,:,1]>=720):raise Rejected('Checkerboard observations leave the captured image')
    centers=np.asarray([np.mean(v.reshape(-1,2),axis=0) for v in image_points]);all_pixels=np.concatenate(image_points).reshape(-1,2)
    span=np.ptp(all_pixels,axis=0)/np.array([960.,720.]);center_span=np.ptp(centers,axis=0)/np.array([960.,720.])
    report=dict(usable_views=len(image_points),inner_corners=[columns,rows],corner_span_fraction=span.tolist(),center_span_fraction=center_span.tolist(),scope='Checkerboard reprojection diagnostic, not independent SLAM pose truth')
    if np.any(span<.65) or np.any(center_span<.15):raise Rejected('Move the board across the image: insufficient image coverage',report)
    result=cv.calibrateCameraExtended(object_points,image_points,(960,720),None,None,flags=0,criteria=(cv.TERM_CRITERIA_EPS+cv.TERM_CRITERIA_COUNT,100,1e-10))
    rms,matrix,distortion,rvecs,tvecs,std_intr,std_ext,errors=result
    errors=errors.reshape(-1);normals=np.asarray([cv.Rodrigues(rv)[0][:,2] for rv in rvecs])
    dots=np.clip(normals@normals.T,-1.,1.);angle=float(np.degrees(np.arccos(dots)).max())
    focal_relative_std=[float(std_intr[0,0]/matrix[0,0]),float(std_intr[1,0]/matrix[1,1])]
    report.update(rms_pixels=float(rms),per_view_rms_pixels=errors.tolist(),normal_spread_degrees=angle,focal_relative_std=focal_relative_std,opencv_version=cv.__version__)
    parameters=source_values(matrix,distortion,meta)
    if not math.isfinite(rms) or rms>.7 or not np.isfinite(errors).all() or float(errors.max())>1.5:raise Rejected('Reprojection error exceeds0.7px overall or1.5px per view',report)
    if angle<15:raise Rejected('Tilt the board: insufficient pose diversity',report)
    if not all(math.isfinite(v) and 0<=v<=.1 for v in focal_relative_std):raise Rejected('Focal uncertainty exceeds10percent',report)
    # Reject a radial polynomial that folds inside the image; the PS model
    # cannot invert it reliably. This is a model check, not metric accuracy.
    fx,fy,cx,cy=matrix[0,0],matrix[1,1],matrix[0,2],matrix[1,2]
    radius=max(((u-cx)/fx)**2+((v-cy)/fy)**2 for u in [0,959] for v in [0,719])
    k1,k2,p1,p2,k3=distortion.reshape(-1)
    r2=np.linspace(0,radius,100)
    if np.any(1+3*k1*r2+5*k2*r2**2+7*k3*r2**3<=0):raise Rejected('Radial model folds within the captured image',report)
    report.update(status='PASS_CHECKERBOARD_FIT',source_camera_values=parameters,cropped_matrix=matrix.tolist(),distortion=distortion.reshape(-1).tolist(),claim='Calibration candidate from this image set; validate on separate images and real motion before accepting SLAM quality')
    return parameters,report

def fit_with_view_rejection(objects,points,meta,pattern):
    """One bounded, absolute per-view gate; all original fit gates still apply."""
    try:
        values,report=fit_observations(objects,points,meta,pattern)
        return values,report,None
    except Rejected as initial:
        if str(initial)!='Reprojection error exceeds0.7px overall or1.5px per view':raise
        errors=initial.report.get('per_view_rms_pixels',[])
        rejected=[i for i,value in enumerate(errors) if not math.isfinite(value) or value>1.5]
        cap=min(3,len(points)//10)
        if len(errors)!=len(points) or not rejected or len(rejected)>cap or len(points)-len(rejected)<15:raise
        kept=[i for i in range(len(points)) if i not in rejected]
        # No repeated pruning or changing thresholds to make a fit pass.
        values,report=fit_observations([objects[i] for i in kept],[points[i] for i in kept],meta,pattern)
        audit=dict(policy='single_refit; per-view RMS>1.5px; at most3 and10percent; retain at least15; all original gates unchanged',initial_fit=initial.report,maximum_exclusions=cap,excluded=[dict(observation_index=i,initial_rms_pixels=errors[i]) for i in rejected])
        return values,report,audit

def make_board(path,pattern=(9,6),square_mm=25.):
    columns,rows=checkerboard_pattern(pattern)
    if not math.isfinite(square_mm) or not .1<=square_mm<=1000:raise Rejected('Invalid square dimension')
    if path.exists():raise RuntimeError('Refuse to overwrite checkerboard')
    path.parent.mkdir(parents=True,exist_ok=True)
    width=(columns+1)*square_mm+30;height=(rows+1)*square_mm+30
    rects='\n'.join(f'<rect x="{15+x*square_mm:g}" y="{15+y*square_mm:g}" width="{square_mm:g}" height="{square_mm:g}" fill="black"/>' for y in range(rows+1) for x in range(columns+1) if (x+y)%2==0)
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}mm" height="{height:g}mm" viewBox="0 0 {width:g} {height:g}">\n<rect width="{width:g}" height="{height:g}" fill="white"/>\n'+rects+'\n</svg>\n',encoding='ascii')
    path.with_suffix('.json').write_text(json.dumps(dict(inner_corners=[columns,rows],squares=[columns+1,rows+1],square_mm=square_mm,white_border_mm=15,print=f'Print100percent; verify the physical{square_mm:g}mm squares with a ruler. Keep the board flat.',scope='Calibration target with15mm print border, not a replica of a commercial plate or a camera calibration'),indent=2)+'\n')

def calibrate(capture,output,square_mm,pattern=(9,6)):
    columns,corner_rows=checkerboard_pattern(pattern)
    if not math.isfinite(square_mm) or not .1<=square_mm<=1000:raise Rejected('Invalid square dimension')
    cv,np=vision()
    if output.exists():raise RuntimeError('Choose a new calibration result directory')
    output.mkdir(parents=True)
    report=dict(status='RUNNING',capture=str(capture),square_mm=square_mm,inner_corners=[columns,corner_rows],input_origin='provided_capture_files; tool does not establish device authenticity',source=[])
    try:
        meta=json.loads((capture/'camera.json').read_text());crop_geometry(meta)
        images=capture/'calibration-frames'
        with (images/'index.csv').open(newline='',encoding='ascii') as index:rows=list(csv.DictReader(index))
        if not 15<=len(rows)<=60:raise Rejected('Need15..60 saved calibration images')
        board=np.zeros((columns*corner_rows,3),np.float32);board[:,:2]=np.mgrid[0:columns,0:corner_rows].T.reshape(-1,2)*square_mm
        objects=[];points=[];digests=set();last_id=-1;last_stamp=-1
        header=b'P5\n960 720\n255\n'
        for row in rows:
            name=row['file'];frame=int(row['frame_index']);stamp=int(row['timestamp_ns'])
            match=re.fullmatch(r'shot_[0-9]+_frame_([0-9]+)\.pgm',name)
            if not match or int(match.group(1))!=frame or frame<=last_id or stamp<=last_stamp or stamp<=0:raise Rejected('Invalid or repeated calibration source identity')
            if (row['width'],row['height'])!=('960','720'):raise Rejected('Calibration frame size differs from capture metadata')
            path=images/name
            if path.resolve().parent!=images.resolve() or path.stat().st_size!=len(header)+960*720:raise Rejected('PGM path/size outside capture contract')
            data=path.read_bytes()
            if not data.startswith(header):raise Rejected('Unexpected calibration PGM header')
            last_id,last_stamp=frame,stamp;digest=hashlib.sha256(data).hexdigest()
            item=dict(file=name,frame=frame,timestamp_ns=stamp,sha256=digest,accepted=False);report['source'].append(item)
            if digest in digests:item['rejection']='duplicate_image';continue
            digests.add(digest);image=np.frombuffer(data[len(header):],dtype=np.uint8).reshape(720,960)
            corners,detection=detect_checkerboard(image,(columns,corner_rows));item['detection']=detection
            if corners is None:item['rejection']=f'no_complete_{columns}x{corner_rows}_checkerboard';continue
            item['accepted']=True;item['corners']=corners.reshape(-1,2).tolist();objects.append(board.copy());points.append(corners.astype(np.float32))
        report['detected_views']=len(points)
        values,quality,audit=fit_with_view_rejection(objects,points,meta,(columns,corner_rows))
        if audit is not None:
            detected=[item for item in report['source'] if item['accepted']]
            for exclusion in audit['excluded']:
                item=detected[exclusion['observation_index']]
                exclusion.update(file=item['file'],frame=item['frame'],timestamp_ns=item['timestamp_ns'])
                item.update(accepted=False,detected=True,rejection='per_view_reprojection_rms_exceeds1.5px',initial_rms_pixels=exclusion['initial_rms_pixels'])
            report['quality_filter']=audit
        report.update(quality)
        with (output/'camera_source.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['width','height','fx','fy','cx','cy','d0','d1','d2','d3','d4']);writer.writerow(values)
        (output/'camera.json').write_text(json.dumps(meta,indent=2)+'\n')
        return report
    except Rejected as error:report.update(error.report,status='REJECTED',reason=str(error));return report
    except Exception as error:report.update(status='ERROR',reason=str(error));raise
    finally:(output/'calibration_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--make-board',type=Path);p.add_argument('--capture',type=Path);p.add_argument('--output',type=Path);p.add_argument('--square-mm',type=float,default=25.);p.add_argument('--columns',type=int,default=9,help='Inner corners along the long edge, not square count');p.add_argument('--rows',type=int,default=6,help='Inner corners along the short edge');args=p.parse_args()
    if not math.isfinite(args.square_mm) or not .1<=args.square_mm<=1000:p.error('Invalid square dimension')
    try:pattern=checkerboard_pattern((args.columns,args.rows))
    except Rejected as error:p.error(str(error))
    if args.make_board:
        if args.capture or args.output:p.error('Choose board generation or calibration')
        make_board(args.make_board,pattern,args.square_mm);print('CHECKERBOARD_READY',args.make_board);return 0
    if not args.capture or not args.output:p.error('Need --capture and --output')
    report=calibrate(args.capture.resolve(),args.output.resolve(),args.square_mm,pattern);print(json.dumps({k:report.get(k) for k in ['status','reason','inner_corners','usable_views','rms_pixels','normal_spread_degrees']},indent=2));return 0 if report['status']=='PASS_CHECKERBOARD_FIT' else 2
if __name__=='__main__':raise SystemExit(main())
