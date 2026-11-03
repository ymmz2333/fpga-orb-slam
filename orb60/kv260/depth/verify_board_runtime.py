"""Verify native runtime/linkage and required PS plugins without creating a DPU runner."""
import argparse
import ctypes
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
from orb60.dense.kv260.common import digest,save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();root=a.root.resolve();prefix=root/'runtime_vai25'
    a.output.mkdir(parents=True,exist_ok=False)
    record={'status':'NATIVE_RUNTIME_CHECK_FAILED','hardware_inference_verified':False,'automatic_firmware_loading':False}
    try:
        if platform.machine()!='aarch64':raise ValueError('Native AArch64 board required')
        os.environ['XLNX_DISABLE_LOAD_XCLBIN']='1'
        modules={};dependencies=[]
        for name in ('xir','vart','target_factory','vitis_ai_library','tools_extra_ops'):
            module=importlib.import_module(name);path=Path(module.__file__).resolve()
            if not path.is_relative_to(prefix):raise ValueError('Module outside private runtime: '+name)
            architecture=subprocess.check_output(['file',str(path)],text=True)
            linked=subprocess.check_output(['ldd',str(path)],text=True)
            if 'ARM aarch64' not in architecture or 'not found' in linked:raise ValueError('ABI/link failure: '+name)
            dependencies.append(str(path)+'\n'+linked)
            modules[name]={'file':str(path.relative_to(prefix)),'sha256':digest(path),'architecture':architecture.strip()}
        from vitis_ai_library import GraphRunner
        if not callable(GraphRunner.create_graph_runner):raise ValueError('GraphRunner entry is absent')
        placement=json.loads((root/'models/placement.json').read_text())
        if digest(root/'models/midas_kv260_b4096.xmodel')!=placement['model_sha256']:raise ValueError('Installed model hash differs')
        required=sorted({op['type'] for op in placement['ps_operations']})
        # Load exactly the reviewed plugins; no graph, calculation or device is created.
        loaded=[]
        for kind in required:
            if kind not in {'data-fix','fix2float','float2fix','relu','upsample-fix'}:raise ValueError('Unexpected model PS plugin: '+kind)
            library=prefix/'lib'/('libvart_op_imp_'+kind+'.so')
            loaded.append(ctypes.CDLL(str(library)))
        bound=loaded[required.index('relu')].kv260_ps_relu_model_sha256
        bound.restype=ctypes.c_char_p
        if bound().decode()!=placement['model_sha256']:raise ValueError('PS ReLU plugin belongs to another model')
        files={str(path.relative_to(prefix)):digest(path) for path in sorted(prefix.rglob('*')) if path.is_file() and not path.is_symlink()}
        links={str(path.relative_to(prefix)):os.readlink(path) for path in sorted(prefix.rglob('*')) if path.is_symlink()}
        save(a.output/'runtime_manifest.json',{'sha256':files,'symlinks':links})
        (a.output/'dependencies.txt').write_text('\n'.join(dependencies))
        record.update(status='NATIVE_RUNTIME_ABI_AND_REQUIRED_PS_LIBRARIES_PASS',modules=modules,required_ps_plugins=required,
                      manifest_sha256=digest(a.output/'runtime_manifest.json'),dependencies_sha256=digest(a.output/'dependencies.txt'),
                      model_sha256=placement['model_sha256'],scope='native imports/linkage/plugin loading; no DPU execution')
    except Exception as error:
        record['error']=str(error);save(a.output/'state.json',record);raise
    save(a.output/'state.json',record);print(json.dumps(record),flush=True)


if __name__=='__main__':main()
