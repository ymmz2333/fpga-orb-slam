"""Reproducible focal ±10% YAMLs, leaving principal point and distortion unchanged."""
import argparse,hashlib,json,pathlib,re
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(); p.add_argument('--base',type=pathlib.Path,default=ROOT/'configs/c/tello_oafd_960x720_provisional.yaml'); a=p.parse_args()
    base=a.base.read_text(encoding='utf-8'); rows=[]
    for label,factor in [('09',.9),('11',1.1)]:
        text=base
        for field in ('fx','fy'):
            key='Camera1.'+field; value=float(re.search(r'^'+re.escape(key)+r': ([^\n]+)',base,re.M).group(1))
            text=re.sub(r'^'+re.escape(key)+r':.*$',key+': '+repr(value*factor),text,flags=re.M)
        text=text.replace('# Provisional borrowed','# Sensitivity: fx/fy x '+str(factor)+'; other settings unchanged.\n# Provisional borrowed')
        output=a.base.parent/('tello_oafd_focal_'+label+'_provisional.yaml')
        output.write_text(text,encoding='utf-8',newline='\n'); rows.append(dict(factor=factor,file=output.name,sha256=hashlib.sha256(output.read_bytes()).hexdigest()))
    print(json.dumps(rows))
if __name__=='__main__': main()
