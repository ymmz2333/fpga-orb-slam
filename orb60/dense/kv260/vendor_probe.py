"""Bounded diagnostics for the exact installed Vitis AI API and float graph."""
import json
from pathlib import Path
import torch
from pytorch_nndct.apis import torch_quantizer
from nndct_shared.utils import NndctOption
from .common import load_midas,read_tensor,save,INPUT_SHAPE
from .metrics import evaluate
import numpy as np
import shutil


def main():
    root=Path('orb60/build');samples=root/'dense/samples-midas';out=root/'kv260'
    torch.set_num_threads(4)
    print('EXPORT_APIS',[x for x in dir(torch_quantizer) if 'export' in x],flush=True)
    print('RELU_OPTIONS',[(x,getattr(NndctOption,x).value) for x in dir(NndctOption) if 'relu' in x],flush=True)
    NndctOption.nndct_relu6_replace.value='reluk'
    model=load_midas(root/'dense/assets');x=torch.from_numpy(read_tensor(samples/'kf_00.input.f32',INPUT_SHAPE))
    with torch.no_grad():eager=model(x).numpy()
    probe=out/'vendor_probe';probe.mkdir(exist_ok=True)
    for name in ['quant_info.json','bias_corr.pth']:
        if (out/'quantized'/name).exists():shutil.copyfile(out/'quantized'/name,probe/name)
    quantizer=torch_quantizer('test',model,(x,),output_dir=str(probe),bitwidth=8,device=torch.device('cpu'))
    print('QUANTIZER_APIS',[x for x in dir(quantizer) if 'export' in x],flush=True)
    NndctOption.nndct_quant_off.value=True
    with torch.no_grad():converted=quantizer.quant_model(x).numpy()
    reference=np.load(root/'dense/midas-small-fp16/kf_00.reference.npy')
    report={'eager_vs_original':evaluate(reference,eager),'quant_off_vs_original':evaluate(reference,converted)}
    save(out/'vendor_probe.json',report);print(json.dumps(report),flush=True)

if __name__=='__main__':main()
