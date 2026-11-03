"""Run actual model PS operators via the official CPU-only run_op interface."""
import argparse,json,re
from pathlib import Path
import numpy as np
from orb60.dense.kv260.common import digest,save

def filename(tensor):
    name=tensor.name
    while re.search(r'\([^()]*\)',name):name=re.sub(r'\([^()]*\)','',name)
    if '(' in name or ')' in name:raise ValueError('Unexpected XIR tensor suffix')
    return name.replace('/','_')+'.bin'

def main():
    p=argparse.ArgumentParser();p.add_argument('model',type=Path);p.add_argument('golden',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    record={'status':'PS_RELU_NUMERICAL_FAILED','hardware_inference_verified':False,'dpu_runner_created':False}
    try:
        import xir,tools_extra_ops
        manifest=json.loads((a.golden/'manifest.json').read_text())
        if digest(a.model)!=manifest['model_sha256']:raise ValueError('Golden model mismatch')
        graph=xir.Graph.deserialize(str(a.model));results=[];aliases=[]
        # The vendor run_op writes tensor names as filenames. Compiler-generated
        # names exceed ext4's 255-byte component limit. Alias only tensor names
        # in a diagnostic copy; operation names, shapes, attributes and data stay.
        for index,case in enumerate(manifest['cases']):
            op=graph.get_op(case['name'])
            for kind,tensor in [('input',op.get_input_op('input',0).get_output_tensor()),('output',op.get_output_tensor())]:
                short=f'ps_relu_{index}_{kind}'
                aliases.append({'original':tensor.name,'alias':short});tensor.name=short
        fixture=a.output/'tensor_alias_test_fixture.xmodel';graph.serialize(str(fixture))
        record.update(test_fixture_sha256=digest(fixture),tensor_name_aliases=aliases,deployment_model_modified=False)
        for index,case in enumerate(manifest['cases']):
            op=graph.get_op(case['name']);input_tensor=op.get_input_op('input',0).get_output_tensor();output_tensor=op.get_output_tensor()
            if input_tensor.dims!=case['shape'] or output_tensor.dims!=case['shape'] or input_tensor.dtype!='float32':raise ValueError('Native operator tensor contract differs')
            value=a.golden/case['input'];reference=a.golden/case['expected']
            if digest(value)!=case['input_sha256'] or digest(reference)!=case['expected_sha256']:raise ValueError('Golden tensor corrupted')
            folder=a.output/f'case_{index}';inputs=folder/'input';outputs=folder/'output';inputs.mkdir(parents=True);outputs.mkdir()
            (inputs/filename(input_tensor)).write_bytes(value.read_bytes())
            if not tools_extra_ops.test_op_run(str(fixture),case['name'],str(inputs),str(outputs)):raise RuntimeError('Native CPU operator failed')
            actual=np.fromfile(outputs/filename(output_tensor),dtype='<f4');expected=np.fromfile(reference,dtype='<f4')
            np.testing.assert_array_equal(actual.view(np.uint32),expected.view(np.uint32))
            results.append({'name':case['name'],'elements':len(actual),'bit_exact':True,
                            'input_sha256':case['input_sha256'],'output_sha256':digest(outputs/filename(output_tensor))})
        if len(results)!=4:raise ValueError('All four reviewed operations must execute')
        if digest(a.model)!=manifest['model_sha256']:raise ValueError('Deployment model was modified')
        record.update(status='NATIVE_PS_RELU_FOUR_MODEL_NODES_BIT_EXACT_PASS',model_sha256=manifest['model_sha256'],reference=manifest['reference'],cases=results)
    except Exception as error:
        record['error']=str(error);save(a.output/'state.json',record);raise
    save(a.output/'state.json',record);print(json.dumps(record),flush=True)

if __name__=='__main__':main()
