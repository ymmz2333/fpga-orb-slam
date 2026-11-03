"""Snapshot retained kernels, select 2/4PPC and K26/64-bit AXI; preserve baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[3]


def prepare(kernel,output,period,ppc=None):
    source=ROOT/'orb60/build/handoff/zynq7015_20261022/fpga_baseline'/kernel
    if output.exists():raise ValueError('New output required')
    # Verify every retained input against its release manifest before reuse.
    omitted=[]
    for row in json.loads((source/'source_manifest.json').read_text()):
        path=source/'inputs'/Path(row['Path'].replace('\\','/'))
        if not path.exists() and path.suffix=='.pyc' and '__pycache__' in path.parts:
            omitted.append(row['Path']);continue  # Non-source cache omitted by retained archive.
        if hashlib.sha256(path.read_bytes()).hexdigest().lower()!=row['SHA256'].lower():
            raise ValueError('Retained source hash mismatch: '+str(path))
    output.mkdir(parents=True)
    shutil.copytree(source/'inputs',output/'inputs')
    if kernel=='descriptor':shutil.copytree(source/'descriptor_vectors',output/'descriptor_vectors')
    status=json.loads((source/'status.json').read_text())
    defines={
        'ORB60_DESCRIPTOR_WIDTH_MODE':status['DescriptorWidthMode'],
        'ORB60_DESCRIPTOR_PREFETCH':status['DescriptorPrefetch'],
        'ORB60_DESCRIPTOR_PATCH32':int(status['DescriptorPatch32']),
        'ORB60_DESCRIPTOR_MOMENT_FUSION':status['DescriptorMomentFusion'],
        'ORB60_DESCRIPTOR_FAST_QUANTIZE':status['DescriptorFastQuantize'],
        'ORB60_SLICE_COMPACT_MODE':status['SliceCompactMode'],
        'ORB60_LAYER_PPC':status['LayerPpc'],
        'ORB60_FAST_STAGED':int(status['FastStaged']),
        'ORB60_LAYER_IO_OVERLAP':int(status['LayerIoOverlap']),
        'ORB60_LAYER_BRAM_FIFOS':int(status['LayerBramFifos']),
    }
    if ppc is not None:
        if ppc not in (2,4):raise ValueError('Only retained 2PPC and 4PPC implementations exist')
        defines['ORB60_LAYER_PPC']=ppc
    recipe={'kernel':kernel,'part':'xck26-sfvc784-2LV-c','period_ns':period,'m_axi_address_bits':64,
            'defines':defines,'source':'zynq7015_20261022 frozen release; selected parallelism requires numerical and protocol gates','omitted_non_source_cache':omitted,
            'status':'PREPARED_NOT_VERIFIED'}
    (output/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n')
    flags=' '.join(f'-D{k}={v}' for k,v in defines.items())
    text=(ROOT/'orb60/kv260/pl/hls.tcl').read_text().replace('@KERNEL@',kernel).replace('@PERIOD@',str(period)).replace('@FLAGS@',flags)
    (output/'run.tcl').write_text(text,newline='\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kernel',choices=['layer2','descriptor'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--period',type=float,default=6.666667)
    p.add_argument('--ppc',type=int,choices=[2,4])
    a=p.parse_args();prepare(a.kernel,a.output.resolve(),a.period,a.ppc)
