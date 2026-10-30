"""P1: two-hour checked memtester stress, frequency evidence, cold-cache hashes.

Never starts SLAM or B3. An error preserves the failed highest-frequency run
and executes the two explicitly authorized comparison conditions for diagnosis.
"""
import argparse,csv,datetime,hashlib,json,os,pathlib,re,signal,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parent.parent
DMC=pathlib.Path('/sys/class/devfreq/dmc')

def privileged_write(path,value):
    subprocess.run(['sudo','-n','tee',str(path)],input=str(value)+'\n',text=True,
        stdout=subprocess.DEVNULL,check=True)

def memory():
    return {k:int(v.split()[0]) for k,v in (line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())}

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def memory_log_ok(text):
    # The board's rktoolkit memtester uses a checked summary rather than Done.
    failures=[int(n) for n in re.findall(r'had found (\d+) failures',text)]
    failed=bool(re.search(r'FAILURE|Status:\s*FAIL|had found [1-9]\d* failures',text))
    finished='Done.' in text or bool(failures and all(n==0 for n in failures) and 'Status: PASS' in text)
    return finished and not failed

def cold_hashes(output,datasets):
    rows=[]
    with (output/'png_hashes.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['round','dataset','frame_index','timestamp_ns','expected_sha256','actual_sha256','match'])
        writer.writeheader()
        for run in range(1,4):
            subprocess.run(['sync'],check=True);privileged_write('/proc/sys/vm/drop_caches',3)
            for dataset in datasets:
                with (dataset/'frames.csv').open() as g:frames=list(csv.DictReader(g))
                for frame in frames:
                    actual=sha(dataset/'mav0/cam0/data'/(frame['timestamp_ns']+'.png'))
                    row=dict(round=run,dataset=dataset.name,frame_index=frame['frame_index'],timestamp_ns=frame['timestamp_ns'],
                        expected_sha256=frame['sha256'],actual_sha256=actual,match=actual==frame['sha256'])
                    writer.writerow(row);rows.append(row)
            f.flush()
    return dict(rounds=3,checks=len(rows),mismatches=sum(not r['match'] for r in rows))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,default=7200)
    p.add_argument('--power-spec',required=True);p.add_argument('--diagnostic-short',action='store_true');a=p.parse_args()
    if a.seconds<7200 and not a.diagnostic_short:raise SystemExit('P1 requires >=7200 seconds')
    out=pathlib.Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
    policies=sorted(pathlib.Path('/sys/devices/system/cpu/cpufreq').glob('policy*'))
    original={str(policy/'scaling_governor'):(policy/'scaling_governor').read_text().strip() for policy in policies}
    original.update({str(DMC/key):(DMC/key).read_text().strip() for key in ('governor','min_freq','max_freq')})
    if memory()['SwapTotal']!=0:raise SystemExit('Experiments require swap=0')
    frequencies=sorted(map(int,(DMC/'available_frequencies').read_text().split()));target=frequencies[-1]
    if int(original[str(DMC/'max_freq')])!=target:raise SystemExit('Existing DMC cap differs from highest available')
    state=dict(status='PREPARING',phase='environment',conditions=[],power_spec=a.power_spec,
        input_voltage_v=None,input_voltage_note='No exposed input-voltage sensor; adapter profiles are not negotiated voltage',
        available_dmc_hz=frequencies,original_settings=original,duration_per_condition_s=a.seconds,
        diagnostic_only=a.diagnostic_short,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        b3_started=False,memory_tool='memtester',tool_sha256=sha(pathlib.Path('/usr/bin/memtester')),
        script_sha256=sha(pathlib.Path(__file__)))
    def save():
        temp=out/'state.tmp';temp.write_text(json.dumps(state,indent=2,ensure_ascii=False));temp.replace(out/'state.json')
    sensors={}
    for policy in policies:
        for key in ('scaling_cur_freq','scaling_max_freq'):sensors[policy.name+'_'+key]=policy/key
    for path in pathlib.Path('/sys/class/thermal').glob('thermal_zone*/temp'):sensors[path.parent.name+'_temp_mc']=path
    for key in ('cur_freq','min_freq','max_freq'):sensors['dmc_'+key]=DMC/key
    os.sched_setaffinity(0,{0,1,2,3});process=None
    def interrupted(signum,frame):raise RuntimeError('P1 interrupted by signal %s'%signum)
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    save()
    try:
        for policy in policies:privileged_write(policy/'scaling_governor','performance')
        conditions=[('performance',target)]
        cursor=0
        while cursor<len(conditions):
            governor,frequency=conditions[cursor];cursor+=1
            directory=out/('%02d_%s_%d'%(cursor,governor,frequency));directory.mkdir()
            privileged_write(DMC/'governor',original[str(DMC/'governor')])
            privileged_write(DMC/'min_freq',original[str(DMC/'min_freq')]);privileged_write(DMC/'max_freq',original[str(DMC/'max_freq')])
            if governor=='fixed':
                privileged_write(DMC/'max_freq',frequency);privileged_write(DMC/'min_freq',frequency)
                privileged_write(DMC/'governor','performance')
            else:privileged_write(DMC/'governor',governor)
            time.sleep(1)
            if governor!='dmc_ondemand' and int((DMC/'cur_freq').read_text())!=frequency:
                raise RuntimeError('Requested DDR test condition did not become active')
            subprocess.run(['sync'],check=True);privileged_write('/proc/sys/vm/drop_caches',3)
            available=memory()['MemAvailable'];mib=int(available*.70/1024)
            # Only a small fixture for diagnostic mode; never qualifies for P1.
            if a.diagnostic_short:mib=16
            command=['sudo','-n','taskset','-c','4-7','memtester',str(mib)+'M','1']
            item=dict(condition=governor,requested_dmc_hz=frequency,command=command,mem_available_before_kb=available,
                requested_memory_mib=mib,status='RUNNING',samples=0,cpu_drop=False,dmc_drop=False,affinity_violations=[],observed_worker_masks=[],start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            state['conditions'].append(item);state.update(status='RUNNING',phase='memory_stress',current=directory.name);save()
            started=time.monotonic()
            with (directory/'memtester.log').open('wb') as log,(directory/'telemetry.csv').open('w',newline='') as telemetry:
                writer=csv.DictWriter(telemetry,fieldnames=['elapsed_s','utc','MemAvailable_kb']+list(sensors));writer.writeheader()
                process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                item['supervised_pid']=process.pid;save()
                while True:
                    values={name:int(path.read_text()) for name,path in sensors.items()}
                    writer.writerow(dict(elapsed_s=time.monotonic()-started,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),MemAvailable_kb=memory()['MemAvailable'],**values));telemetry.flush()
                    item['samples']+=1
                    pending=[process.pid];seen=set()
                    while pending:
                        pid=pending.pop()
                        if pid in seen:continue
                        seen.add(pid)
                        try:
                            pending.extend(map(int,pathlib.Path('/proc/%d/task/%d/children'%(pid,pid)).read_text().split()))
                            if pathlib.Path('/proc/%d/comm'%pid).read_text().strip()!='memtester':continue
                            for task in pathlib.Path('/proc/%d/task'%pid).iterdir():
                                mask=sorted(os.sched_getaffinity(int(task.name)))
                                if mask not in item['observed_worker_masks']:item['observed_worker_masks'].append(mask)
                                if not set(mask)<={4,5,6,7}:item['affinity_violations'].append(dict(pid=pid,tid=int(task.name),mask=mask))
                        except (ProcessLookupError,FileNotFoundError):pass
                    item['cpu_drop']|=any(values[policy.name+'_scaling_cur_freq']<int((policy/'cpuinfo_max_freq').read_text()) for policy in policies if set(map(int,(policy/'affected_cpus').read_text().split())) & {4,5,6,7})
                    if governor!='dmc_ondemand':item['dmc_drop']|=values['dmc_cur_freq']!=frequency
                    item['max_temperature_c']=max(item.get('max_temperature_c',0),max(v/1000 for k,v in values.items() if k.endswith('_temp_mc')))
                    code=process.poll();item['elapsed_s']=time.monotonic()-started;save()
                    if code is not None:
                        item['cycles_complete']=item.get('cycles_complete',0)+1
                        log.flush()
                        item['completed_cycles_log_ok']=memory_log_ok((directory/'memtester.log').read_text(errors='replace'))
                        if code!=0 or not item['completed_cycles_log_ok'] or item['elapsed_s']>=a.seconds:break
                        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                        item['supervised_pid']=process.pid;save()
                    if item['elapsed_s']>a.seconds+1800:raise RuntimeError('memtester exceeded requested duration plus 1800 s finishing allowance')
                    time.sleep(.5)
            text=(directory/'memtester.log').read_text(errors='replace')
            allocated=[int(n) for n in re.findall(r'got\s+\d+MB\s*\((\d+) bytes\)',text)]
            item['allocated_bytes_per_cycle']=allocated
            item['requested_memory_verified']=bool(allocated and all(n==mib*1024*1024 for n in allocated))
            item.update(exit_code=code,zero_error_status=bool(code==0 and memory_log_ok(text) and item.get('cycles_complete',0)),
                elapsed_s=time.monotonic()-started)
            item['status']='PASS' if item['zero_error_status'] and item['requested_memory_verified'] and item['elapsed_s']>=a.seconds and item['observed_worker_masks'] and not(item['cpu_drop'] or item['dmc_drop'] or item['affinity_violations']) else 'FAIL'
            save();print('P1_CONDITION_DONE %s status=%s'% (directory.name,item['status']),flush=True)
            if cursor==1 and not item['zero_error_status']:
                conditions.extend([('dmc_ondemand',target),('fixed',frequencies[-2])])
        state.update(phase='cold_cache_png_hashes',current=None);save()
        datasets=[ROOT/d['path'] for d in json.loads((ROOT/'configs/b2/design_candidates.json').read_text())['datasets'] if d['kind']=='prepared']
        state['hash_checks']=cold_hashes(out,datasets)
        for name,command in [('dmesg.log',['sudo','-n','dmesg']),('kernel_journal.log',['sudo','-n','journalctl','-k','-b','--no-pager'])]:
            with (out/name).open('wb') as f:subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
        passed=state['conditions'][0]['status']=='PASS' and not state['hash_checks']['mismatches']
        state['status']=('DIAGNOSTIC_ONLY' if passed else 'DIAGNOSTIC_FAIL') if a.diagnostic_short else ('PASS' if passed else 'FAIL')
    except Exception as error:state.update(status='FAIL',error=str(error))
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(['sudo','-n','kill','-TERM','--','-'+str(process.pid)],check=False)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(['sudo','-n','kill','-KILL','--','-'+str(process.pid)],check=False);process.wait(timeout=10)
        restoration=[]
        for path,value in original.items():
            try:privileged_write(path,value);restoration.append(pathlib.Path(path).read_text().strip()==value)
            except Exception as error:state.setdefault('restore_errors',[]).append(str(error));restoration.append(False)
        state['settings_restored']=all(restoration)
        if not state['settings_restored']:state['status']='FAIL'
        state['ended_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print('P1_RESULT status=%s restored=%s output=%s'%(state['status'],state['settings_restored'],out),flush=True)
    return 0 if state['status'] in ('PASS','DIAGNOSTIC_ONLY') else 2
if __name__=='__main__':raise SystemExit(main())
