#!/usr/bin/env python3
"""Generate six single-variable configurations from the unchanged official YAML."""
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPECS = [('baseline_752x480',752,480,1000,8),('half_376x240',376,240,1000,8),
         ('features_500',752,480,500,8),('features_1500',752,480,1500,8),
         ('levels_4',752,480,1000,4),('levels_1',752,480,1000,1)]

def generate():
    directory=ROOT/'configs/a3'
    original=(directory/'EuRoC_official.yaml').read_text()
    base=re.sub(r'^Camera.new(?:Width|Height):.*\n','',original,flags=re.M)
    manifest=[]
    calibration=[458.654,457.296,367.215,248.375]
    for name,width,height,features,levels in SPECS:
        text=re.sub(r'^ORBextractor.nFeatures:.*$', 'ORBextractor.nFeatures: %d'%features,base,flags=re.M)
        text=re.sub(r'^ORBextractor.nLevels:.*$', 'ORBextractor.nLevels: %d'%levels,text,flags=re.M)
        if width!=752:
            text=text.replace('Camera.height: 480','Camera.height: 480\nCamera.newWidth: 376\nCamera.newHeight: 240')
        path=directory/(name+'.yaml'); path.write_bytes(text.encode())
        manifest.append(dict(configuration=name,tracking_width=width,tracking_height=height,
                             nFeatures=features,nLevels=levels,initialization_nFeatures=5*features,
                             resize_policy='none' if width==752 else 'Settings isotropic 0.5',
                             effective_intrinsics=[v*(width/752 if i%2==0 else height/480) for i,v in enumerate(calibration)],
                             settings='configs/a3/'+path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest

if __name__=='__main__':
    print('A3_CONFIGS_READY count=%d initialization_multiplier=5'%len(generate()))
