"""Fetch the checksummed, published FastDepth distribution into the dedicated assets folder."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
from ..common import digest,save

URL='https://media.axelera.ai/artifacts/model_cards/weights/depth_estimation/fast_depth_224x224.onnx'
SHA='7a9f571d9496555bbcc9c46dcb77f1357fb84d3f2608cd38af91fe66c96dfe85'


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args()
    folder=a.root/'orb60/build/kv260/fastdepth/assets';folder.mkdir(parents=True,exist_ok=True);path=folder/'fast_depth_224x224.onnx'
    if not path.exists():
        temporary=path.with_suffix('.part')
        with urllib.request.urlopen(URL,timeout=30) as source,temporary.open('wb') as target:shutil.copyfileobj(source,target)
        if digest(temporary)!=SHA:raise ValueError('FastDepth download SHA256 mismatch')
        temporary.replace(path)
    if digest(path)!=SHA:raise ValueError('FastDepth local asset SHA256 mismatch')
    for name,url in [('LICENSE_FASTDEPTH','https://raw.githubusercontent.com/dwofk/fast-depth/master/LICENSE'),
                     ('model_card.yaml','https://raw.githubusercontent.com/axelera-ai-hub/voyager-sdk/latest/ax_models/zoo/torch/fastdepth-nyudepthv2-onnx.yaml')]:
        if not (folder/name).exists():
            with urllib.request.urlopen(url,timeout=30) as source:(folder/name).write_bytes(source.read())
    save(folder/'source.json',{'url':URL,'sha256':SHA,'md5':hashlib.md5(path.read_bytes()).hexdigest(),
                             'upstream':'https://github.com/dwofk/fast-depth',
                             'distribution':'https://github.com/axelera-ai-hub/voyager-sdk/blob/latest/ax_models/zoo/torch/fastdepth-nyudepthv2-onnx.yaml'})
    print('FASTDEPTH_ASSET_HASH_PASS',SHA)

if __name__=='__main__':main()
