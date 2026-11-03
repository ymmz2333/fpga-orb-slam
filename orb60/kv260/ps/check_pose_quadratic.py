"""Independent NumPy validation of exported C++ normal-equation fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def check(source,output,layout='col'):
    if layout not in ('col','row'):raise ValueError('Explicit Jacobian memory layout required')
    raw=Path(source).read_bytes();values=np.frombuffer(raw,dtype='<f8')
    # A(2x6), information(2x2), error(2), rho, initial H/b, resulting H/b.
    width=12+4+2+1+36+6+36+6
    if len(values)!=256*width or not np.isfinite(values).all():raise ValueError('Incomplete/nonfinite quadratic fixtures')
    worst=0.
    for row in values.reshape(-1,width):
        at=0
        def take(n):
            nonlocal at
            v=row[at:at+n];at+=n;return v
        a=take(12).reshape(2,6,order='F' if layout=='col' else 'C');omega=take(4).reshape(2,2,order='F');error=take(2);rho=take(1)[0]
        initial=take(36).reshape(6,6,order='F');initial_b=take(6)
        h=take(36).reshape(6,6,order='F');b=take(6)
        expected=initial+a.T@(rho*omega)@a;expected_b=initial_b-rho*a.T@omega@error
        delta=max(np.max(np.abs(h-expected))/max(1.,np.max(np.abs(expected))),
                  np.max(np.abs(b-expected_b))/max(1.,np.max(np.abs(expected_b))))
        if not np.isfinite(delta) or delta>1e-12:raise ValueError('Independent normal-equation mismatch')
        worst=max(worst,float(delta))
    result=dict(status='INDEPENDENT_NUMPY_QUADRATIC_PASS',cases=256,max_normalized_error=worst,
                jacobian_layout=layout,
                source_sha256=hashlib.sha256(raw).hexdigest(),scope='Equation component only; actual pose/trajectory gates remain required')
    Path(output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--layout',choices=('col','row'),default='col')
    a=p.parse_args();check(a.source,a.output,a.layout)
