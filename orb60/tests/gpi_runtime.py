"""Task-local embedded CPython bootstrap; never patches cocotb/site-packages."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys


def python_dll():
    buffer=ctypes.create_unicode_buffer(32768)
    query=ctypes.windll.kernel32.GetModuleFileNameW
    query.argtypes=(wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD)
    query.restype=wintypes.DWORD
    if not query(wintypes.HMODULE(sys.dllhandle),buffer,len(buffer)):
        raise OSError('Cannot identify the loaded CPython DLL')
    return Path(buffer.value).resolve()


def prepare(argv):
    """Run before cocotb logging when ModelSim supplies None stdio objects."""
    root=Path(os.environ['ORB60_GPI_DIAGNOSTICS'])
    root.mkdir(parents=True,exist_ok=True)
    repaired=[]
    for name in ('stdout','stderr'):
        if getattr(sys,name) is None:
            stream=(root/f'embedded_{name}.log').open('a',encoding='utf-8',buffering=1)
            setattr(sys,name,stream)
            if getattr(sys,'__'+name+'__') is None:setattr(sys,'__'+name+'__',stream)
            repaired.append(name)
    actual=python_dll();expected=Path(os.environ['ORB60_EXPECT_PYTHON_DLL']).resolve()
    record=dict(version=sys.version,executable=sys.executable,base_prefix=sys.base_prefix,
                loaded_dll=str(actual),expected_dll=str(expected),repaired_stdio=repaired)
    (root/'python_runtime.json').write_text(json.dumps(record,indent=2)+'\n')
    if actual!=expected or sys.version_info[:3]!=(3,12,12):
        raise RuntimeError('Embedded Python differs from the configured 3.12.12 runtime')


def configure(output):
    """Pin the child runtime to the DLL actually loaded by the project venv."""
    dll=python_dll()
    if sys.version_info[:3]!=(3,12,12):raise RuntimeError('Project Python must be 3.12.12')
    os.environ['LIBPYTHON_LOC']=str(dll)
    os.environ['PYTHONHOME']=str(dll.parent)
    os.environ['PYGPI_PYTHON_BIN']=sys.executable
    os.environ['ORB60_EXPECT_PYTHON_DLL']=str(dll)
    os.environ['ORB60_GPI_DIAGNOSTICS']=str(output.resolve())
    defaults=','.join(('cocotb_tools._coverage:start_cocotb_library_coverage',
                       'cocotb.logging:_configure','cocotb._init:init_package_from_simulation',
                       'cocotb._init:run_regression'))
    users=os.environ.get('PYGPI_USERS',defaults)
    prefix='gpi_runtime:prepare'
    if prefix not in users.split(','):users=prefix+','+users
    os.environ['PYGPI_USERS']=users
