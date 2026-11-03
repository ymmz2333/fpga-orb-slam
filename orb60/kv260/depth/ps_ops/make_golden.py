"""Generate independent PyTorch CPU references for the four reviewed ReLU nodes."""
import argparse,json
from pathlib import Path
import numpy as np
import torch
from orb60.dense.kv260.common import digest,save

def main():
    p=argparse.ArgumentParser();p.add_argument('placement',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);placement=json.loads(a.placement.read_text())
    policy=placement['explicit_ps_operator_policy'];review={op['name']:op for op in policy['review']};cases=[]
    for index,op in enumerate(policy['approved_extra_ops']):
        shape=review[op['name']]['output_shape'];rng=np.random.RandomState(20261102+index)
        value=(rng.randn(*shape)*30).astype(np.float32)
        value.flat[:8]=[-np.inf,-100,-1,-0.0,0.0,1,np.inf,np.nan]
        expected=torch.relu(torch.from_numpy(value)).numpy()
        input_path=a.output/f'case_{index}.input.f32';expected_path=a.output/f'case_{index}.expected.f32'
        value.tofile(input_path);expected.tofile(expected_path)
        cases.append({'name':op['name'],'shape':shape,'input':input_path.name,'expected':expected_path.name,
                      'input_sha256':digest(input_path),'expected_sha256':digest(expected_path)})
    save(a.output/'manifest.json',{'model_sha256':placement['model_sha256'],'reference':'PyTorch CPU '+torch.__version__,'cases':cases})

if __name__=='__main__':main()
