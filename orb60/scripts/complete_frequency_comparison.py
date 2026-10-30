"""Select only a clock/PPC candidate with fresh RTL, full route and unit gates."""
import argparse
import json
from pathlib import Path

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def run(job):
    root=read(job/'status.json');records={}
    for ppc in (2,4):
        route=read(job/f'route{ppc}_status.json');frame=read(job/f'frame{ppc}_status.json')
        assert route['State']==frame['State']=='SUCCEEDED'
        routed=read(Path(route['RouteJob'])/'status.json');native=read(Path(frame['FrameJob'])/'status.json')
        assert routed['FrequencyMHz']==125 and routed['LayerPpc']==ppc
        for name in ('LayerHlsJob','DescriptorHlsJob'):assert Path(routed[name]).resolve()==Path(native[name]).resolve()
        performance=read(Path(frame['FrameJob'])/'performance.json')
        assert performance['frequency_mhz']==125 and performance['layer_ppc']==ppc and performance['rtl_unchanged']
        assert len(performance['runs'])==4 and all(r['clock_period_ps']==8000 and r['axi_metric_version']==2 for r in performance['runs'])
        maximum=max(f['milliseconds'] for r in performance['runs'] for f in r['frames'])
        records[str(ppc)]=dict(route=route['RouteJob'],frame=frame['FrameJob'],maximum_modeled_ms=maximum,timing=routed['Timing'])
    unit=Path((job/'merge4_axis_job.txt').read_text(encoding='utf-8-sig').strip())
    assert read(unit/'status.json')['State']=='SUCCEEDED'
    root.update(State='SUCCEEDED',Stage='COMPUTER_GATES_COMPLETE',LayerPpc=4,FrequencyMHz=125,
        Selected='4PPC125MHz',RouteJob=records['4']['route'],FrameJob=records['4']['frame'],MergeAxisJob=str(unit),
        LayerHlsJob=(job/'layer4_hls_job.txt').read_text(encoding='utf-8-sig').strip(),
        DescriptorHlsJob=(job/'descriptor_hls_job.txt').read_text(encoding='utf-8-sig').strip(),
        Comparisons=records,Scope='Fresh8ns2/4PPC125MHz exact computer gates with normalized DDR; PS/board/P99 unverified')
    (job/'status.json').write_text(json.dumps(root,indent=2)+'\n')
    print('FREQUENCY_COMPARISON_COMPLETE',json.dumps(records))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);run(p.parse_args().job)
