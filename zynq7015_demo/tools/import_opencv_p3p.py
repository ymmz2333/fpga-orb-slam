"""Reproduce the dependency-free subset of OpenCV 4.2.0's BSD P3P solver."""
from pathlib import Path
import hashlib
import json
root=Path(__file__).resolve().parents[1]/'vendor/opencv_p3p'
up=root/'upstream'
source=(up/'p3p.cpp').read_text()
start=source.index('p3p::p3p(cv::Mat cameraMatrix)')
end=source.index('p3p::p3p(double',start)
source=source[:start]+source[end:]
start=source.index('bool p3p::solve(cv::Mat&')
end=source.index('bool p3p::solve(double',start)
source=source[:start]+source[end:]
notice='/* Adapted from OpenCV 4.2.0; BSD-3-Clause. See LICENSE and provenance.json.\n   Only cv::Mat wrappers removed; numerical P3P implementation unchanged. */\n'
(root/'p3p.cpp').write_text(notice+source,encoding='utf-8',newline='\n')
header=(up/'p3p.h').read_text()
header=header.replace('#include "precomp.hpp"','#include <algorithm>')
header=header.replace('  p3p(cv::Mat cameraMatrix);','')
start=header.index('  bool solve(cv::Mat&')
end=header.index('  int solve(double',start)
header=header[:start]+header[end:]
start=header.index('  template <typename T>')
end=header.index('  void init_inverse_parameters();',start)
header=header[:start]+header[end:]
(root/'p3p.h').write_text(notice+header,encoding='utf-8',newline='\n')
poly=(up/'polynom_solver.cpp').read_text().replace('#include "precomp.hpp"','static constexpr double CV_PI=3.141592653589793238462643383279502884;')
(root/'polynom_solver.cpp').write_text(notice+poly,encoding='utf-8',newline='\n')
(root/'polynom_solver.h').write_bytes((up/'polynom_solver.h').read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
report=dict(upstream='https://github.com/opencv/opencv/tree/4.2.0/modules/calib3d/src',license='BSD-3-Clause; LICENSE reproduced with binary packages',
    adaptation='Remove cv::Mat overloads/templates and instrumentation; substitute the same double CV_PI constant. Numerical solver unchanged.',
    upstream_sha256={p.name:sha(p) for p in up.iterdir()},subset_sha256={p.name:sha(p) for p in root.iterdir() if p.is_file() and p.name!='provenance.json'})
(root/'provenance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print('P3P subset generated; numerical and board tests still required')
