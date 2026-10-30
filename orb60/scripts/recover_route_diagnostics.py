"""Validate retained routed evidence after a diagnostics-only parser failure."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tkinter

from summarize_diagnostics import summarize


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def recover(job,output):
    origin=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
    assert origin['State']=='FAILED' and origin['Error']=='Missing or inconsistent extended route diagnostics'
    assert origin['FrequencyMHz']==100 and origin['Part']=='xc7z015clg485-2'
    scratch=Path(origin['ScratchRoot'])
    assert (scratch/'vivado/.vivado_timing_success').read_text().strip()=='ORB60_TIMING_PASS'
    for item in json.loads((job/'inputs/ip_manifest.json').read_text(encoding='utf-8-sig')):
        assert sha(scratch/item['Path']).upper()==item['SHA256'],item['Path']
    for item in json.loads((job/'tool_manifest.json').read_text(encoding='utf-8-sig')):
        assert sha(job/'inputs'/item['Path']).upper()==item['SHA256'],item['Path']
    reports=job/'reports'
    metrics=dict(line.split('\t',1) for line in (reports/'post_route_metrics.tsv').read_text().splitlines())
    tcl=tkinter.Tcl();tcl.call('source',str((job/'inputs/timing_checks.tcl').resolve()))
    summary=tcl.call('next_timing_summary_metrics',(reports/'post_route_timing.rpt').read_text())
    tcl.call('next_check_timing_coverage',(reports/'post_route_check_timing.rpt').read_text())
    for name in ('summary_wns_ns','summary_whs_ns','tns_ns','ths_ns','setup_failed_endpoints','hold_failed_endpoints'):
        value=float(tcl.call('dict','get',summary,name));assert value==float(metrics[name])
        assert value>=0 if name.startswith('summary_w') else value==0
    assert float(metrics['wns_ns'])>=0 and float(metrics['whs_ns'])>=0
    route=(reports/'post_route_route_status.rpt').read_text()
    count=lambda label:int(re.search(re.escape(label)+r'[. \t]*:[ \t]*([0-9]+)',route)[1])
    assert count('# of routable nets')==count('# of fully routed nets') and count('# of nets with routing errors')==0
    drc=(reports/'post_route_drc.rpt').read_text()
    drc_rows=[line.split('|')[1:-1] for line in drc.splitlines() if line.startswith('|')]
    issues=[x for x in drc_rows if len(x)==4 and x[1].strip() in {'Error','Critical Warning'}]
    assert not issues
    for item in json.loads((Path(origin['LayerHlsJob'])/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert sha(Path(origin['LayerHlsJob'])/'inputs'/item['Path']).upper()==item['SHA256']
    for item in json.loads((Path(origin['DescriptorHlsJob'])/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert sha(Path(origin['DescriptorHlsJob'])/'inputs'/item['Path']).upper()==item['SHA256']
    frame=Path(origin['FrameJob'])
    assert json.loads((frame/'status.json').read_text())['State']=='SUCCEEDED'
    assert json.loads((frame/'performance.json').read_text())['status']=='PASS'
    checkpoint=scratch/'vivado/next_system_routed.dcp';checkpoint_hash=sha(checkpoint)
    output.mkdir(parents=True,exist_ok=True)
    assert not (output/'status.json').exists(),'Refusing an existing recovery result'
    summarize(reports/'post_route_diagnostics',output/'diagnostics')
    manifest=[dict(path=str(p.resolve()),sha256=sha(p)) for p in reports.rglob('*') if p.is_file()]
    (output/'report_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    shutil.copyfile(Path(__file__),output/'recover_route_diagnostics.py')
    shutil.copyfile(Path(__file__).with_name('summarize_diagnostics.py'),output/'summarize_diagnostics.py')
    assert sha(checkpoint)==checkpoint_hash
    state=dict(State='SUCCEEDED',Stage='ROUTE_DIAGNOSTICS_RECOVERED',OriginJob=str(job.resolve()),
        OriginStateRetained='FAILED',Part=origin['Part'],FrequencyMHz=100,Timing=metrics,
        FrameJob=origin['FrameJob'],LayerHlsJob=origin['LayerHlsJob'],DescriptorHlsJob=origin['DescriptorHlsJob'],
        Checkpoint=str(checkpoint.resolve()),CheckpointSHA256=checkpoint_hash,
        Scope='Existing routed design and strict diagnostics validated; no new CAD/bit/PS/board claim',
        FinishedUtc=datetime.now(timezone.utc).isoformat())
    (output/'status.json').write_text(json.dumps(state,indent=2)+'\n')
    print('ROUTE_DIAGNOSTICS_RECOVERY_PASS WNS='+metrics['wns_ns']+' WHS='+metrics['whs_ns'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();recover(a.job,a.output)
