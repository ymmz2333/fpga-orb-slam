"""Bind the custom PS plugin to the reviewed model and four exact operation names."""
import argparse,json
from pathlib import Path
from orb60.dense.kv260.common import digest,save

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    placement=json.loads((a.root/'models/placement.json').read_text())
    model=digest(a.root/'models/midas_kv260_b4096.xmodel')
    policy=placement['explicit_ps_operator_policy'];ops=policy['approved_extra_ops']
    if model!=placement['model_sha256'] or model!=policy['model_sha256']:raise ValueError('PS policy model hash mismatch')
    if len(ops)!=4 or any(op['type']!='relu' or not op['name'].isascii() for op in ops):raise ValueError('Exactly four reviewed ReLU operations required')
    a.output.mkdir(parents=True,exist_ok=True)
    header='#pragma once\ninline constexpr const char* kv260_relu_names[]{'+','.join(json.dumps(op['name']) for op in ops)+'};\n'
    header+='inline constexpr const char* kv260_relu_model_sha256='+json.dumps(model)+';\n'
    (a.output/'approved_relu.hpp').write_text(header,encoding='utf-8')
    save(a.output/'policy.json',{'model_sha256':model,'ops':ops,'header_sha256':digest(a.output/'approved_relu.hpp')})

if __name__=='__main__':main()
