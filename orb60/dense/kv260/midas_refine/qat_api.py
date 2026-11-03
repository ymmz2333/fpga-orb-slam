import inspect
from pytorch_nndct.nn.modules import functional
from pytorch_nndct import QatProcessor
print('DEPLOY_SOURCE',inspect.getsource(QatProcessor.to_deployable))
for name in ['Pad','Add','Interpolate','ReLU']:
    obj=getattr(functional,name,None)
    if obj:print(name,inspect.signature(obj),inspect.signature(obj.forward),inspect.getsource(obj)[:2000])
