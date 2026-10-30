"""Reuse a completed layer unit gate only for identical frozen RTL/tests/vectors."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def data(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def checked_manifest(root,name):
    entries=data(root/name);result={}
    for entry in entries:
        path=entry['Path'].replace('\\','/')
        assert hashlib.sha256((root/path).read_bytes()).hexdigest().upper()==entry['SHA256']
        result[path]=entry['SHA256']
    return result


def reuse(previous,current,layer,kernel='layer2'):
    state=data(previous/'status.json');hls=data(layer/'status.json')
    assert state['State']=='SUCCEEDED' and state['Stage']=='COMPLETE'
    origin_key='LayerHlsJob' if kernel=='layer2' else 'DescriptorHlsJob'
    assert Path(state[origin_key]).resolve()==layer.resolve(),'Different frozen IP'
    assert hls['State']=='SUCCEEDED' and hls['Cosim'] and hls['Kernel']==kernel
    assert hls['Part']=='xc7z015clg485-2' and 5<=hls['PeriodNs']<=10
    # HLS manifest paths are relative to inputs, unlike the protocol test manifest.
    for entry in data(layer/'source_manifest.json'):
        assert hashlib.sha256((layer/'inputs'/entry['Path']).read_bytes()).hexdigest().upper()==entry['SHA256']
    old_tests=checked_manifest(previous,'test_manifest.json');new_tests=checked_manifest(current,'test_manifest.json')
    actual_tests=lambda entries:{k:v for k,v in entries.items() if k.startswith(('inputs/tests/','inputs/common/'))}
    assert actual_tests(old_tests)==actual_tests(new_tests), 'Protocol tests/model changed'
    proof=previous/kernel;unit=data(proof/'status.json');result=data(proof/'result.json');config=data(proof/'config.json')
    assert unit['state']=='SUCCEEDED' and unit['kernel']==kernel
    assert Path(unit['hls_job']).resolve()==layer.resolve()
    cases,reset_case=([7,1,14],14) if kernel=='layer2' else ([35,30,24,25,36,37],7)
    assert result['status']=='PASS' and result['transactions']==len(cases)
    assert result['reset_interruption'] and result['direct_completion_barrier']
    assert config['cases']==cases and config['reset_case']==reset_case
    assert config.get('clock_period_ps',10000)==round(hls['PeriodNs']*1000),'Protocol clock differs from immutable source IP'
    assert [r['case'] for r in result['cases']]==config['cases']
    vectors=layer/('oracle_vectors' if kernel=='layer2' else 'descriptor_vectors');assert Path(config['vectors']).resolve()==vectors.resolve()
    for name,digest in data(vectors/'vectors.json')['sha256'].items():
        assert hashlib.sha256((vectors/name).read_bytes()).hexdigest()==digest
    rtl=layer/f'projects/{kernel}/solution1/syn/verilog'
    retained={e['name']:e['sha256'] for e in data(proof/'rtl_manifest.json')}
    actual={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in rtl.iterdir() if p.suffix in ('.v','.sv','.dat')}
    assert retained==actual,'Layer RTL changed since the retained protocol test'
    destination=current/kernel;destination.mkdir(exist_ok=False)
    for name in ('status.json','result.json','config.json','rtl_manifest.json'):
        shutil.copyfile(proof/name,destination/name)
    record=dict(scope='Reused identical completed isolated RTL/random AXI/reset/barrier evidence; no new unit simulation',kernel=kernel,
                previous_protocol=str(previous.resolve()),layer_hls_job=str(layer.resolve()),rtl_files=len(actual),
                tests_identical=True,vectors_hash_checked=True,rtl_identical=True)
    (destination/'reuse.json').write_text(json.dumps(record,indent=2)+'\n')
    print(kernel.upper()+'_PROTOCOL_REUSE_PASS identical_rtl_tests_vectors')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('previous','current','layer'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--kernel',choices=('layer2','descriptor'),default='layer2')
    a=p.parse_args();reuse(a.previous,a.current,a.layer,a.kernel)
