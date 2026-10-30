"""Linux compilation probe: unmodified command, resource usage, process-tree RSS and sensors."""
import argparse,csv,datetime,json,os,pathlib,resource,signal,subprocess,time
def process_rss_tree(root):
    parents={}; rss={}
    for path in pathlib.Path('/proc').glob('[0-9]*/stat'):
        try:
            parts=path.read_text().rsplit(')',1)[1].split(); pid=int(path.parent.name)
            parents[pid]=int(parts[1]); rss[pid]=int(parts[21])*os.sysconf('SC_PAGE_SIZE')//1024
        except (OSError,ValueError,IndexError): continue
    children={root}; old=0
    while old!=len(children):
        old=len(children); children.update(pid for pid,parent in parents.items() if parent in children)
    return sum(rss.get(pid,0) for pid in children)
def sensors():
    fields={}
    for path in pathlib.Path('/sys/devices/system/cpu/cpufreq').glob('policy*'):
        for name in ('scaling_governor','scaling_cur_freq','scaling_max_freq'):
            fields[path.name+'_'+name]=(path/name).read_text().strip()
    dmc=pathlib.Path('/sys/class/devfreq/dmc')
    for name in ('governor','cur_freq','max_freq'): fields['dmc_'+name]=(dmc/name).read_text().strip()
    for path in pathlib.Path('/sys/class/thermal').glob('thermal_zone*/temp'): fields[path.parent.name+'_temp_mc']=path.read_text().strip()
    for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
        key=line.split(':',1)[0]
        if key in ('MemAvailable','SwapTotal','SwapFree'): fields[key+'_kb']=int(line.split()[1])
    return fields
def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=pathlib.Path,required=True); p.add_argument('command',nargs=argparse.REMAINDER); a=p.parse_args()
    command=a.command[1:] if a.command and a.command[0]=='--' else a.command
    a.output.mkdir(parents=True,exist_ok=False); start=time.monotonic(); peak=0; proc=None
    info=dict(command=command,start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        kernel_uptime_start_s=float(pathlib.Path('/proc/uptime').read_text().split()[0]),
        rlimit_stack_bytes=resource.getrlimit(resource.RLIMIT_STACK),rlimit_as_bytes=resource.getrlimit(resource.RLIMIT_AS),
        affinity=sorted(os.sched_getaffinity(0)),before=sensors(),sampling_interval_s=.5)
    def stop(signum,frame):
        if proc and proc.poll() is None: os.killpg(proc.pid,signal.SIGTERM)
        raise RuntimeError('Probe interrupted')
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    with (a.output/'build.log').open('wb') as log,(a.output/'samples.csv').open('w',newline='') as f:
        initial=sensors(); writer=csv.DictWriter(f,fieldnames=['elapsed_s','tree_rss_kb']+list(initial)); writer.writeheader()
        proc=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True)
        while True:
            rss=process_rss_tree(proc.pid); peak=max(peak,rss)
            writer.writerow(dict(elapsed_s=time.monotonic()-start,tree_rss_kb=rss,**sensors())); f.flush()
            code=proc.poll()
            if code is not None: break
            time.sleep(.5)
    info.update(exit_code=code,elapsed_s=time.monotonic()-start,after=sensors(),
        sampled_tree_peak_rss_kb=peak,max_child_process_rss_kb=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        kernel_uptime_end_s=float(pathlib.Path('/proc/uptime').read_text().split()[0]))
    for file,cmd in [('journal_kernel.log',['sudo','-n','journalctl','-k','-b','--no-pager','-o','short-monotonic']),('dmesg.log',['sudo','-n','dmesg'])]:
        with (a.output/file).open('wb') as f: info[file+'_exit']=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
    (a.output/'result.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    print('COMPILE_PROBE_COMPLETE exit=%d peak_process_rss_kb=%d sampled_tree_rss_kb=%d output=%s'%
        (code,info['max_child_process_rss_kb'],peak,a.output),flush=True)
    return code
if __name__=='__main__': raise SystemExit(main())
