import argparse
from pathlib import Path
import shutil
p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--dense',required=True,type=Path)
a=p.parse_args()
for name,old,new in [('FpgaORB.h','return int(count);','return int(DenseFilterFeatures(keys,descriptors,extractor->GetScaleFactors()));'),
                     ('FpgaPipeline.h','return int(f.count);','return int(DenseFilterFeatures(keys,descriptors,extractor->GetScaleFactors()));')]:
    path=a.source/'include'/name;text=path.read_text()
    if 'DenseFilterFeatures(' not in text:
        backup=a.source/'include'/(name+'.before_dense_mask')
        if backup.exists():raise ValueError('Unexpected mask backup already exists')
        shutil.copy2(path,backup)
        if text.count(old)!=1:raise ValueError('Unexpected feature adapter anchor')
        text=text.replace(old,new)
        if name=='FpgaORB.h':text=text.replace('#include "ORBextractor.h"','#include "ORBextractor.h"\n#include "DenseFeatureMask.h"')
        path.write_text(text)
shutil.copy2(a.dense/'slam/DenseFeatureMask.h',a.source/'include/DenseFeatureMask.h')
print('OPTIONAL_VALIDITY_MASK_INSTALLED_DEFAULT_UNCHANGED')
