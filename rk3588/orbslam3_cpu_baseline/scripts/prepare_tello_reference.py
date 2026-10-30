"""Convert pinned third-party intrinsics to a provisional ORB-SLAM3 v1.0 YAML.

This performs schema conversion, not camera calibration or SLAM evaluation.
Resolution must match the source: a crop cannot be handled by rescaling K.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import cv2

COMMIT = '41f98f3fb53c3250187efc55c2893373dc32cfbc'
SOURCE_SHA256 = 'c6a130727d77874d8521cea82927faadad7256409d63bd2cc08547d6574d58b7'
SOURCE_URL = f'https://github.com/geturin/OAFD_Monocular/blob/{COMMIT}/config/tello.yaml'
ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', type=Path, default=ROOT/'reports/c0')
    p.add_argument('--output', type=Path, default=ROOT/'configs/c/tello_oafd_960x720_provisional.yaml')
    a = p.parse_args()
    reference = a.report/'references/config_tello.yaml'
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError('Pinned reference SHA256 mismatch')
    source = cv2.FileStorage(str(reference), cv2.FILE_STORAGE_READ)
    if not source.isOpened():
        raise ValueError('Cannot read reference YAML')
    fields = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2']
    camera = {}
    for name in fields:
        node = source.getNode('Camera.'+name)
        if node.empty():
            raise ValueError('Missing reference parameter: '+name)
        camera[name] = node.real()
    width, height = [int(source.getNode('Camera.'+s).real()) for s in ('width','height')]
    source_fps = source.getNode('Camera.fps').real()
    source.release()
    with (a.report/'inventory.csv').open(encoding='utf-8', newline='') as f:
        clips = list(csv.DictReader(f))
    if not clips or any((int(c['width']),int(c['height'])) != (width,height) for c in clips):
        raise ValueError('Recording dimensions differ from reference: require a new calibration/crop decision')
    if any(c['nominal_fps'] != '30/1' for c in clips):
        raise ValueError('Dataset nominal FPS needs a separate decision')
    text = ['%YAML:1.0', '', '# 临时内参，待标定后重跑；借用另一台 Tello 的参数，未标定本机。',
            '# Provisional borrowed intrinsics, NOT a calibration of this aircraft.',
            '# Source: '+SOURCE_URL, '# Source SHA256: '+digest,
            '# Same 960x720 dimensions; EIS/crop/device equivalence is unverified.',
            '# Camera.fps is nominal 30; replay waits must use actual selected timestamps.',
            'File.version: "1.0"', 'Camera.type: "PinHole"']
    text += [f'Camera1.{k}: {v!r}' for k,v in camera.items()]
    text += [f'Camera.width: {width}', f'Camera.height: {height}', 'Camera.fps: 30.0',
             'Camera.RGB: 0', '', '# A3/B1 extractor configuration (initialization uses 5000 features).',
             'ORBextractor.nFeatures: 1000', 'ORBextractor.scaleFactor: 1.2',
             'ORBextractor.nLevels: 8', 'ORBextractor.iniThFAST: 20', 'ORBextractor.minThFAST: 7', '',
             'Viewer.KeyFrameSize: 0.05', 'Viewer.KeyFrameLineWidth: 1.0', 'Viewer.GraphLineWidth: 0.9',
             'Viewer.PointSize: 2.0', 'Viewer.CameraSize: 0.08', 'Viewer.CameraLineWidth: 3.0',
             'Viewer.ViewpointX: 0.0', 'Viewer.ViewpointY: -0.7', 'Viewer.ViewpointZ: -3.5', 'Viewer.ViewpointF: 500.0']
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text('\n'.join(text)+'\n',encoding='utf-8',newline='\n')
    # Verify actual OpenCV parser output, not only the generated string.
    saved = cv2.FileStorage(str(a.output),cv2.FILE_STORAGE_READ)
    for k,v in camera.items():
        if saved.getNode('Camera1.'+k).real() != v:
            raise ValueError('Converted parameter mismatch: '+k)
    if not saved.getNode('Camera.newWidth').empty() or not saved.getNode('Tbc').empty():
        raise ValueError('Unexpected resize/IMU setting')
    saved.release()
    provenance = dict(status='PROVISIONAL_SCHEMA_CHECK_PASSED',camera_calibrated=False,
        source_url=SOURCE_URL,source_commit=COMMIT,source_sha256=digest,
        source_fps=source_fps,output_fps=30.0,width=width,height=height,intrinsics=camera,
        output_yaml=str(a.output.resolve()),output_sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),
        differences=['Camera.* intrinsics -> Camera1.* for File.version 1.0',
            'Nominal FPS 20 -> 30 from C0; timestamps still require C0 confirmation',
            'No resize; omit IMU/Tbc; retain borrowed distortion, no invented k3'],
        limitations=['No checkerboard observations or own-camera reprojection error',
            'Actual camera, firmware, EIS and crop equivalence unverified'],
        future_calibration='May use K as CALIB_USE_INTRINSIC_GUESS; must optimize from own checkerboard observations')
    (a.report/'reference_intrinsics.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False),encoding='utf-8')
    print('PROVISIONAL_YAML_VERIFIED '+str(a.output))

if __name__ == '__main__':
    main()
