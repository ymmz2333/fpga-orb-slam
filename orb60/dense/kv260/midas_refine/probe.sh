#!/usr/bin/env bash
set -eo pipefail
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python - <<'PY'
import inspect
from pytorch_nndct.apis import torch_quantizer
from nndct_shared.utils import NndctOption
print('API',inspect.signature(torch_quantizer))
print('API_INTERNALS','\n'.join(l for l in inspect.getsource(torch_quantizer).splitlines() if 'self.' in l)[:9000])
from pytorch_nndct.qproc.base import TorchQuantProcessor
print('PROCESSOR_INTERNALS','\n'.join(l for l in inspect.getsource(TorchQuantProcessor).splitlines() if 'quantizer' in l)[:6000])
print('OPTIONS',[(n,getattr(NndctOption,n).value) for n in dir(NndctOption) if any(s in n for s in ['corr','equal','quant_method','stat'])])
print('FINETUNE_OPTIONS',[(n,getattr(NndctOption,n).value) for n in dir(NndctOption) if any(s in n for s in ['finetune','adaquant'])])
from pytorch_nndct.qproc.adaquant import AdvancedQuantProcessor
src=inspect.getsource(AdvancedQuantProcessor.finetune)
print('FINETUNE_TAIL',src[-10000:])
print('FINITE_LAYER',inspect.getsource(AdvancedQuantProcessor.finetune_layer)[:6000])
from pathlib import Path
p=Path('/opt/vitis_ai/conda/envs/vitis-ai-pytorch/lib/python3.7/site-packages/nndct_shared/quantization/quant_config.py')
lines=p.read_text().splitlines()
for i,l in enumerate(lines):
 if any(s in l for s in ['method','calib','percentile']):print(i+1,l)
print('\nCONFIG_DEFAULTS\n'+'\n'.join(lines[25:90]))
print('\nCONFIG_PARSER\n'+'\n'.join(lines[140:210]))
p=p.parents[1]/'quantization/base_quantizer.py'
if p.exists():
 for i,l in enumerate(p.read_text().splitlines()):
  if any(s in l for s in ['statistic','quant_config_file','quant_strategy']):print(i+1,l)
p=Path('/opt/vitis_ai/conda/envs/vitis-ai-pytorch/lib/python3.7/site-packages/pytorch_nndct/quantization/torchquantizer.py')
lines=p.read_text().splitlines()
for i,l in enumerate(lines):
 if any(s in l for s in ['calib_statistic','statistic','mode(', 'fix_pos_history']):
  print('QUANTIZER',i+1,'\n'.join(lines[max(0,i-3):i+5]))
PY
