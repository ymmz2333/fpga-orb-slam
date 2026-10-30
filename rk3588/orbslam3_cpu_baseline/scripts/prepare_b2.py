"""Materialize approved design candidates without touching source camera YAMLs."""
import argparse,hashlib,json,pathlib,re
ROOT=pathlib.Path(__file__).resolve().parent.parent

def prepare(output,plan_path=None):
    output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=False)
    plan_path=pathlib.Path(plan_path or ROOT/'configs/b2/design_candidates.json')
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    if plan['initialization_multiplier']!=5:raise ValueError('B1/C1 SLAM initialization extractor requires multiplier 5')
    def resolve(value):
        p=pathlib.Path(value).expanduser();return str(p if p.is_absolute() else ROOT/p)
    datasets=[dict(d) for d in plan['datasets']]
    for d in datasets:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',d['name']):raise ValueError('Unsafe dataset name')
        for key in ('path','timestamps','yaml'):d[key]=resolve(d[key])
    (output/'candidate_plan.json').write_bytes(plan_path.read_bytes())
    for d in datasets:
        stamps=pathlib.Path(d['timestamps']).read_text().splitlines()
        if len(stamps)<plan['smoke_frames']:raise ValueError('Not enough smoke frames: '+d['name'])
        target=output/d['name'];target.mkdir()
        (target/'smoke_timestamps.txt').write_text('\n'.join(stamps[:plan['smoke_frames']])+'\n')
        d.update(full_frames=len(stamps),smoke_frames=plan['smoke_frames'],smoke_timestamps=str(target/'smoke_timestamps.txt'),configs={})
        original=pathlib.Path(d['yaml']).read_text(encoding='utf-8')
        if re.search(r'^Camera(?:1)?\.new(?:Width|Height):',original,re.M):raise ValueError('Unexpected resize in baseline')
        d['source_yaml_sha256']=hashlib.sha256(pathlib.Path(d['yaml']).read_bytes()).hexdigest()
        for variant,options in plan['variants'].items():
            text=original
            fields={'nFeatures':plan['normal_features'],'nLevels':options.get('levels',plan['default_levels']),
                'scaleFactor':options.get('scale',plan['default_scale']),'iniThFAST':plan['ini_fast'],'minThFAST':plan['min_fast']}
            for key,value in fields.items():
                text,count=re.subn(r'(?m)^(ORBextractor\.'+key+r':)\s*[^\n]+',lambda m:m[1]+' '+str(value),text)
                if count!=1:raise ValueError('Missing or ambiguous YAML field '+key)
            text+='\n# 设计候选；特征生成端使用，SLAM 忽略 Design 字段。\n'
            for key in ('fixed_fast','grid','angle_bins','skip_blur','box2','mean_rounding'):
                text+='Design.%s: %d\n'%(key,options.get(key,0))
            text+='Design.initialization_multiplier: %d\n'%plan['initialization_multiplier']
            text+='Design.probe_thresholds: ['+', '.join(str(v) for v in plan['fast_probe_thresholds'])+']\n'
            config=target/(variant+'.yaml');config.write_text(text,encoding='utf-8')
            d['configs'][variant]=str(config)
    manifest=dict(plan=plan,datasets=datasets,scope='B2 fixed first-600-frame smoke; no B3 formal runs',
                  plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest())
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    return manifest
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--plan');a=p.parse_args()
    m=prepare(a.output,a.plan);print('B2_PREPARED datasets=%d configs=%d'%(len(m['datasets']),len(m['plan']['variants'])))
