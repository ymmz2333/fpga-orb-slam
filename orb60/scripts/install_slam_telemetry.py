"""Apply optional read-only telemetry on top of the accepted0018 pipeline."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);a=p.parse_args();source=a.source.resolve()
    patches=a.workspace.resolve()/'rk3588/orbslam3_cpu_baseline/patches'
    patch=patches/'0019-slam-visualization-telemetry.patch'
    if subprocess.run(['git','apply','--reverse','--check','-C0',str(patch)],cwd=source,capture_output=True).returncode:
        subprocess.run(['git','apply','--check',str(patch)],cwd=source,check=True)
        subprocess.run(['git','apply',str(patch)],cwd=source,check=True)
    shutil.copy2(patches/'OrbTelemetry.h',source/'include/OrbTelemetry.h')
    print('OPTIONAL_READ_ONLY_TELEMETRY_INSTALLED')


if __name__=='__main__':main()
