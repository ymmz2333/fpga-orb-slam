"""Explicit DPU+points metadata generation; no FPGA or XRT load."""
import argparse,json
from pathlib import Path
from orb60.kv260.pl.prepare_dpu_metadata import prepare

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[3]
    kernel=root/'orb60/build/kv260_system/vendor_sources/dpu_trd/DPUCZDX8G/prj/Vitis/kernel_xml/dpu/kernel.xml'
    print(json.dumps(prepare(a.job,kernel,a.output,expected_kind='dpu_points')))
