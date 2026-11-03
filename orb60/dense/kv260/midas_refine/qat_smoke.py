"""Check vendor full-QAT graph and gradients without taking an optimizer step."""
import os
from pathlib import Path
import torch
from pytorch_nndct import QatProcessor
from pytorch_nndct.nn import QuantStub,DeQuantStub
from pytorch_nndct.nn.modules.functional import Pad
from ..common import load_midas,read_tensor,INPUT_SHAPE,save


def main():
    root=Path('/workspace/orb60/build');out=root/'kv260/midas_refine/qat-smoke';out.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(2);os.chdir(out)
    report={'status':'RUNNING','optimizer_steps':0,'hardware_verified':False}
    save(out/'result.json',report)
    try:
        model=load_midas(root/'dense/assets',static_padding=True)
        x=torch.from_numpy(read_tensor(root/'kv260/replay_inputs/inputs/m0_k5.input.f32',INPUT_SHAPE))
        with torch.no_grad():target=model(x).detach()
        # Replace the export-only subclass by exact standard padding + convolution modules.
        replacements=[]
        class BoundPad(torch.nn.Module):
            def __init__(self,padding):
                super().__init__();self.operation=Pad();self.padding=padding
            def forward(self,value):return self.operation(value,self.padding,'constant',0)
        for name,layer in list(model.named_modules()):
            if type(layer).__name__=='Conv2dSameExport':
                conv=torch.nn.Conv2d(layer.in_channels,layer.out_channels,layer.kernel_size,layer.stride,
                                     layer.padding,layer.dilation,layer.groups,layer.bias is not None)
                conv.weight=layer.weight;conv.bias=layer.bias
                parts=name.split('.');parent=model
                for part in parts[:-1]:parent=getattr(parent,part)
                setattr(parent,parts[-1],torch.nn.Sequential(BoundPad(layer.pad.padding),conv));replacements.append(name)
        with torch.no_grad():rewritten=model(x)
        if not torch.equal(target,rewritten):raise ValueError('QAT module rewrite changed float result')
        report['exact_conv_rewrites']=replacements
        class Scoped(torch.nn.Module):
            def __init__(self,net):
                super().__init__();self.quant=QuantStub();self.net=net;self.dequant=DeQuantStub()
            def forward(self,value):return self.dequant(self.net(self.quant(value)))
        model=Scoped(model).eval()
        # Apply the complete explicit Add/Interpolate/Pad adaptation as needed by QAT.
        from .qat_model import prepare
        model=prepare(model.net)
        with torch.no_grad():
            if not torch.equal(model(x),target):raise ValueError('Explicit QAT graph changed float output')
        model.train()
        processor=QatProcessor(model,(x,),bitwidth=8,device=torch.device('cpu'))
        student=processor.trainable_model(allow_reused_module=True);student.train()
        prediction=student(x);loss=((prediction-target)/target.std()).square().mean();loss.backward()
        grads={n:float(p.grad.norm()) for n,p in student.named_parameters() if p.grad is not None}
        if not grads or not all(torch.isfinite(p.grad).all() for p in student.parameters() if p.grad is not None):raise ValueError('Invalid QAT gradients')
        report.update(status='QAT_GRADIENT_SMOKE_PASS',loss=float(loss.detach()),gradient_tensors=len(grads),gradients=grads)
        report['control_methods']=[n for n in dir(student) if any(s in n for s in ['quant','bn_stats','fuse'])]
    except Exception as e:
        report.update(status='FAILED',error=repr(e));save(out/'result.json',report);raise
    save(out/'result.json',report)

if __name__=='__main__':main()
