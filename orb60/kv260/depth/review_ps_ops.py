"""Explicit model-bound policy for the QAT graph's four PS ReLU boundaries."""
import json
from pathlib import Path
import xir
from orb60.dense.kv260.common import digest,save

root=Path('/workspace/orb60/build/kv260_system/depth_midas_qat')
model=root/'compiled/midas_kv260_b4096.xmodel';source=root/'export/runtime/Scoped_0_int.xmodel'
graph=xir.Graph.deserialize(str(model));parent=graph.get_root_subgraph();rows=[];conv=0
for sub in parent.toposort_child_subgraph():
    device=str(sub.get_attr('device')).upper() if sub.has_attr('device') else 'USER'
    for op in sub.get_ops():
        kind=op.get_type().lower()
        if 'conv' in kind:
            if device!='DPU':raise ValueError('CPU convolution is forbidden')
            conv+=1
        if device!='DPU' and kind=='relu':
            attrs=op.get_attrs()
            rows.append({'name':op.get_name(),'type':kind,'attrs':attrs,'output_shape':op.get_output_tensor().dims,'device':device})
if len(rows)!=4 or not conv:raise ValueError('Unexpected QAT PS operation boundary')
policy={'schema':1,'model_sha256':digest(model),'source_model_sha256':digest(source),
        'approved_extra_ops':[{'name':r['name'],'type':'relu'} for r in rows],
        'equivalent_ps_operation':'elementwise maximum(x, 0); no weights or convolution',
        'review':rows,'dpu_convolutions':conv,'status':'EXPLICIT_PS_RELU_POLICY_BOARD_UNTESTED'}
save(root/'ps_operator_policy.json',policy)
print(json.dumps({'relu_count':len(rows),'convolutions_in_dpu':conv,'details':rows}),flush=True)
