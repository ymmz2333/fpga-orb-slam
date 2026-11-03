"""Read a compiled model using native XIR; no runner or hardware is launched."""
import argparse
import json
from pathlib import Path
import platform
from orb60.dense.kv260.common import digest,save
from orb60.dense.kv260.placement import validate_placement
from orb60.dense.kv260.preflight import fingerprints


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('model','placement','output'):p.add_argument(name,type=Path)
    a=p.parse_args();record={'status':'NATIVE_XIR_CHECK_FAILED','hardware_inference_verified':False}
    try:
        if platform.machine()!='aarch64':raise ValueError('Native board Python required')
        import xir
        expected=json.loads(a.placement.read_text(encoding='utf-8'))
        if digest(a.model)!=expected['model_sha256']:raise ValueError('Model hash differs from compiler placement')
        graph=xir.Graph.deserialize(str(a.model));root=graph.get_root_subgraph()
        children=[root] if root.is_leaf else list(root.toposort_child_subgraph())
        groups=[];actual=fingerprints(root.get_attrs())
        for child in children:
            actual.update(fingerprints(child.get_attrs()))
            groups.append({'name':child.get_name(),'device':str(child.get_attr('device')).upper() if child.has_attr('device') else 'USER',
                           'ops':[{'name':op.get_name(),'type':op.get_type()} for op in sorted(child.get_ops(),key=lambda op:op.get_name())]})
        if groups!=expected['subgraphs']:raise ValueError('Native graph differs from compiler placement')
        policy=expected.get('explicit_ps_operator_policy',{}).get('approved_extra_ops',[])
        result=validate_placement(groups,policy)
        if sorted(actual)!=sorted(expected['fingerprints']):raise ValueError('Native model fingerprint differs')
        for key in ('dpu_subgraphs','convolutions'):
            if result[key]!=expected[key]:raise ValueError('Native placement count differs: '+key)
        record.update(status='NATIVE_XIR_DESERIALIZE_PLACEMENT_PASS',model_sha256=digest(a.model),placement_sha256=digest(a.placement),
                      dpu_subgraphs=result['dpu_subgraphs'],convolutions_all_in_dpu=result['convolutions'],fingerprints=sorted(actual),
                      xir_module=xir.__file__,scope='native ABI and model parsing only; no DPU execution')
    except Exception as error:
        record['error']=str(error);save(a.output,record);raise
    save(a.output,record);print(json.dumps(record),flush=True)


if __name__=='__main__':main()
