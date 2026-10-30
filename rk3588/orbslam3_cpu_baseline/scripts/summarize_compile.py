"""Reproduce resource and kernel evidence summaries from measure_compile output."""
import argparse,csv,json,pathlib,re

def summarize(folder):
    folder=pathlib.Path(folder)
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    with (folder/'samples.csv').open(encoding='utf-8',newline='') as f:
        samples=list(csv.DictReader(f))
    faults={}
    for name in ('journal_kernel.log','dmesg.log'):
        faults[name]=[line for line in (folder/name).read_text(encoding='utf-8',errors='replace').splitlines()
            if re.search(r'out of memory|oom-kill|killed process|segfault|hardware error|edac',line,re.I)]
    summary=dict(exit_code=result['exit_code'],elapsed_s=result['elapsed_s'],samples=len(samples),
        max_child_process_rss_kb=result['max_child_process_rss_kb'],
        sampled_tree_peak_rss_kb=result['sampled_tree_peak_rss_kb'],
        min_mem_available_kb=min(int(s['MemAvailable_kb']) for s in samples),
        max_temperature_c=max(int(v) for s in samples for k,v in s.items() if k.endswith('_temp_mc'))/1000,
        swap_total_kb=sorted({int(s['SwapTotal_kb']) for s in samples}),
        governors_before={k:v for k,v in result['before'].items() if k.endswith('governor')},
        governors_after={k:v for k,v in result['after'].items() if k.endswith('governor')},
        kernel_fault_matches=faults,
        limitations='RSS process maximum and sampled process-tree maximum differ; kernel logs cannot exclude unlogged hardware faults')
    with (folder/'summary.json').open('w',encoding='utf-8',newline='\n') as f:
        json.dump(summary,f,ensure_ascii=False,indent=2); f.write('\n')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('folder'); a=p.parse_args()
    print(json.dumps(summarize(a.folder),ensure_ascii=False))
