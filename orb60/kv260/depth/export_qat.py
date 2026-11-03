"""Export the visually accepted QAT state without changing its failed numeric record."""
import argparse
import json
from pathlib import Path
from orb60.dense.kv260.common import digest,save
from orb60.dense.kv260.midas_refine.video_test import QatReference


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path('/workspace');build=root/'orb60/build';a.output.mkdir(parents=True,exist_ok=False)
    selection=json.loads((root/'orb60/kv260/config/depth_model_selection.json').read_text())
    if not selection['user_visual_acceptance']:raise ValueError('Explicit visual acceptance required')
    if digest(root/selection['weights'])!=selection['weights_sha256']:raise ValueError('Selected checkpoint mismatch')
    import os
    os.chdir(a.output)
    record={'status':'EXPORT_STARTED','weights_sha256':selection['weights_sha256'],'numerical_acceptance':'FAILED_ORIGINAL_THRESHOLDS','user_visual_acceptance':True,'hardware_verified':False}
    try:
        engine=QatReference(build,a.output)
        engine.processor.export_xmodel(str(a.output/'runtime'))
        models=list((a.output/'runtime').glob('*.xmodel'))
        if len(models)!=1:raise ValueError('Exactly one exported QAT XIR model required')
        record.update(status='QAT_XIR_EXPORTED_BOARD_UNTESTED',model=models[0].name,model_sha256=digest(models[0]))
        save(a.output/'compile_gate.json',{'status':'QUANTIZATION_FAILED','checkpoint_sha256':selection['weights_sha256'],
            'reproduction_status':json.loads((a.output/'reproduction.json').read_text())['status'],
            'artifacts':{models[0].name:digest(models[0])}})
    except Exception as e:record.update(status='FAILED',error=repr(e));raise
    finally:save(a.output/'export.json',record)


if __name__=='__main__':main()
