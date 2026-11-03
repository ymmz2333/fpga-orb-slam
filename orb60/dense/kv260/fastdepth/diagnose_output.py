"""Separate terminal INT8 representation error from full-network quantization error."""
import argparse
import json
from pathlib import Path
import numpy as np
from .bridge import to_inverse
from ..tensors import quantize,dequantize
from ..metrics import evaluate
from ..common import save


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args()
    folder=a.root/'orb60/build/kv260/fastdepth';config=json.loads((folder/'quantized/quant_info.json').read_text())
    name,setting=list(config['output'].items())[-1];fix=setting[1];rows=[]
    for i in range(20):
        name='kf_%02d'%i;native=np.load(folder/'reference'/(name+'.native.npy'))
        value=dequantize(quantize(native,fix),fix);inverse=to_inverse(value)
        row={'id':name,'depth_max':float(native.max()),'saturated_pixels':int((native>127*2.**-fix).sum()),
             **evaluate(np.load(folder/'reference'/(name+'.reference.npy')),inverse)}
        row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98;rows.append(row)
    report={'status':'DIAGNOSTIC_ONLY','backend':'host terminal quantization simulation, not full model or hardware',
            'fix_point':fix,'representable_depth_max':127*2.**-fix,'frames':rows,'passed':sum(r['passed'] for r in rows),
            'worst_nrmse':max(r['normalized_rmse'] for r in rows),'minimum_spearman':min(r['spearman'] for r in rows)}
    save(folder/'terminal_quantization_diagnostic.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='frames'}))

if __name__=='__main__':main()
