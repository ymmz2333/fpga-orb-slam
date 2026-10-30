"""Generate authored synthetic JPEGs and independent Pillow luminance references."""
from pathlib import Path
import json,hashlib
from PIL import Image,features
root=Path(__file__).resolve().parents[1];out=root/'tests/fixtures/camera';out.mkdir(parents=True,exist_ok=True)
entries=[]
for width,height,subsampling,mode in [(1280,720,2,'RGB'),(1280,800,0,'L'),(960,720,1,'RGB'),(1024,768,0,'RGB')]:
    channels=3 if mode=='RGB' else 1;data=bytearray(width*height*channels)
    for y in range(height):
        for x in range(width):
            base=(y*width+x)*channels;data[base]=(x*17+y*3+(x//31)*13)%256
            if channels==3:data[base+1]=(x*5+y*11)%256;data[base+2]=(x*13+y*7)%256
    image=Image.frombytes(mode,(width,height),bytes(data));name=f'{width}x{height}_{mode}_{subsampling}'
    image.save(out/(name+'.jpg'),quality=87,subsampling=subsampling,progressive=False)
    with Image.open(out/(name+'.jpg')) as reference:
        reference.draft('L',reference.size);reference.load();assert reference.mode=='L' and reference.size==(width,height)
        left=(width-960)//2;top=(height-720)//2
        (out/(name+'.gray')).write_bytes(reference.crop((left,top,left+960,top+720)).tobytes())
    entries.append(dict(name=name,width=width,height=height,mode=mode,subsampling=subsampling))
    if width==960:
        image.save(out/'progressive.jpg',quality=87,progressive=True)
        image.convert('CMYK').save(out/'cmyk.jpg',quality=87)
files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.suffix in ('.jpg','.gray')}
(out/'manifest.json').write_text(json.dumps(dict(origin='Authored coordinate formulas in tools/generate_camera_fixtures.py',reference='Pillow JPEG decoder draft L, then explicit center crop; no RGB-to-gray conversion',pillow_version=Image.__version__,libjpeg_turbo=features.version_feature('libjpeg_turbo'),cases=entries,sha256=files),indent=2)+'\n')
print('CAMERA_FIXTURES_GENERATED',len(files))
