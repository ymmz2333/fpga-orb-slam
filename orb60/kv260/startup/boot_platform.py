"""PS/systemd cold-boot initialization, explicitly enabled by the operator.

Reuse the verified firmware -> interfaces -> driver sequence once per boot.
Never retry a failed load or reprogram a running platform.
"""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path


def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    p=Path(p);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8');tmp.replace(p)


def checked_paths(root,config):
    result={}
    for key,value in config['paths'].items():
        path=(root/value).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('Missing/outside startup asset: '+key)
        result[key]=path
    for relative,expected in config['sha256'].items():
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or digest(path)!=expected:raise ValueError('Startup asset changed: '+relative)
    return result


def refreshed_config(original,root,folder,uio):
    value=dict(original)
    value.update(deployment_receipt=str((folder/'deployment/deployment_receipt.json').relative_to(root)),
                 point_preflight=str((folder/'checks/point_preflight.json').relative_to(root)),
                 preflight=str((folder/'checks/dpu_preflight.json').relative_to(root)),point_uio=uio)
    return value


def run(root,config_path):
    import pwd
    root=Path(root).resolve();config=load(config_path);paths=checked_paths(root,config)
    if os.geteuid()!=0:raise ValueError('Boot platform service must run as root')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    folder=root/'startup_runtime'/boot;folder.mkdir(parents=True,exist_ok=True)
    status=folder/'PLATFORM.json'
    if status.exists():
        previous=load(status)
        if previous['status']!='READY':raise RuntimeError('This boot already attempted initialization; no automatic retry')
        sys.path.insert(0,str(root/'sources'))
        from orb60.kv260.two_board_session import verify_current_platform
        current=load(paths['camera_config'])
        verify_current_platform(root,current,{'kv_deployment_receipt':current['deployment_receipt']})
        print('CURRENT_BOOT_ALREADY_READY',flush=True);return
    record=dict(status='INITIALIZING',boot_id=boot,stage='WAIT_STARTER',no_kernel_or_boot_image_changes=True)
    save(status,record)
    pending=root/'startup_runtime/PENDING_INIT.json'
    def command(name,args,timeout=90,user=False):
        record['stage']=name;save(status,record)
        if user:args=['runuser','-u',config['user'],'--']+args
        with (folder/(name+'.log')).open('wb') as log:
            subprocess.run(args,cwd=root/'sources',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=timeout)
    try:
        if pending.exists():raise RuntimeError('An earlier platform initialization did not finish; inspect it before loading again')
        deadline=time.monotonic()+90
        starter=Path('/sys/kernel/config/device-tree/overlays/k26-starter-kits_image_1/status')
        while not starter.exists() or starter.read_text().strip()!='applied':
            if time.monotonic()>deadline:raise TimeoutError('Factory starter overlay did not become ready')
            time.sleep(.5)
        base=paths['base_preparation'].parent;assets=paths['phased_manifest'].parent
        save(pending,dict(boot_id=boot,status='COLD_BOOT_INIT_IN_PROGRESS',output=str(folder)))
        for stage in ('firmware','interfaces','driver'):
            command(stage,[sys.executable,'-m','orb60.kv260.point_pl.deploy_phased','--base',str(base),
                '--assets',str(assets),'--output',str(folder/'deployment'),'--stage',stage,
                '--tagged-export',str(paths['tagged_export']),'--module',str(paths['module']),'--load'])
        receipt=load(folder/'deployment/deployment_receipt.json')
        owner=pwd.getpwnam(config['user']);checks=folder/'checks';checks.mkdir()
        os.chown(checks,owner.pw_uid,owner.pw_gid)
        runtime=['bash',str(paths['runtime']),str(root),'python','-m']
        command('point_preflight',runtime+['orb60.kv260.point_pl.board_smoke','--uio',receipt['point_uio'],
            '--abi',str(paths['abi']),'--release',str(paths['release']),
            '--deployment-receipt',str(folder/'deployment/deployment_receipt.json'),
            '--memory-backend','native-dpu','--output',str(checks/'point_preflight.json')],user=True)
        command('dpu_preflight',runtime+['orb60.dense.kv260.preflight','--arch',str(paths['arch']),
            '--profile',str(paths['profile']),'--expected-xrt-prefix',config['expected_xrt_prefix'],
            '--driver','vivado','--output',str(checks/'dpu_preflight.json')],user=True)
        current=load(paths['camera_config']);save(folder/'previous_camera_config.json',current)
        updated=refreshed_config(current,root,folder,receipt['point_uio'])
        sys.path.insert(0,str(root/'sources'))
        from orb60.kv260.two_board_session import verify_current_platform
        verify_current_platform(root,updated,{'kv_deployment_receipt':updated['deployment_receipt']})
        save(paths['camera_config'],updated);os.chown(paths['camera_config'],owner.pw_uid,owner.pw_gid)
        record.update(status='READY',stage='COMPLETE',point_uio=receipt['point_uio'],
                      receipt=str(folder/'deployment/deployment_receipt.json'),camera_config_sha256=digest(paths['camera_config']))
        pending.unlink()
    except BaseException as e:record.update(status='FAILED',error=repr(e));raise
    finally:save(status,record)
    print(json.dumps(record),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    a=p.parse_args();run(a.root,a.config)
