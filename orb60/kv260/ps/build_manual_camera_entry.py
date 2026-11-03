"""Build only a manual camera main; retain the verified mapping DSO unchanged."""
import argparse,json,platform,subprocess,time
from pathlib import Path
from .build_network_adapter import digest
from .build_pose_variant import available


def transform(text):
    changes=[
      ('const size_t limit=std::stoull(argv[7]);','const size_t limit=std::stoull(argv[7]);size_t processed=0;const char* manual_stop=std::getenv("ORB60_MANUAL_STOP_FILE");'),
      ('require(limit>0&&limit<=36000,"Finite camera frame count required");','require(limit==0&&manual_stop&&manual_stop[0]==\'/\',"Explicit manual stop file and no frame limit required");'),
      ('KvNetwork::CameraPipeline input(argv[3],limit,out+"/camera_profile.json");','KvNetwork::CameraPipeline input(argv[3],0,out+"/camera_profile.json",true);'),
      ('for(size_t i=0;i<limit;++i) {','for(size_t i=0;;++i) {\n            if(i>=2&&!access(manual_stop,F_OK)){input.requestStop();input.joinProducer();}\n            KvNetwork::CameraFrame f;if(!input.next(i,f))break;const bool final_frame=input.drained();'),
      ('require(!stopping,"Explicitly stopped: partial run is not accepted");auto f=input.get(i);','require(!stopping,"Interrupted manual run is not accepted");'),
      ('i+1==limit,&raw.keys','final_frame,&raw.keys'),
      ('if((i+1)%30==0||i+1==limit)', 'processed=i+1;\n            if((i+1)%30==0||final_frame)'),
      ('    const double seconds=', '    require(!access(manual_stop,F_OK)&&processed>=2,"Manual completion requires operator stop and drained input");\n    atomic_json(out+"/manual_stop.json","{\\"status\\":\\"OPERATOR_STOP_DRAINED\\",\\"frames\\":"+std::to_string(processed)+"}");\n    const double seconds='),
    ]
    for old,new in changes:
        if text.count(old)!=1:raise ValueError('Unreviewed manual camera boundary: '+old)
        text=text.replace(old,new)
    # Only summary fields use the old finite count after the input scope.
    at=text.index('    const double seconds=');head,tail=text[:at],text[at:]
    if tail.count('limit')!=4:raise ValueError('Unreviewed camera summary frame count')
    return head+tail.replace('limit','processed')


def run(root,base,output):
    root,base,output=map(lambda x:Path(x).resolve(),(root,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Actual KV260 and1536MiB compiler margin required')
    old=json.loads((base/'BUILD.json').read_text());assert old['status']=='NATIVE_CAMERA_ENTRY_BUILD_PASS'
    before={**old['protected_sha256'],**old['products_sha256']}
    before.update({str(base/'source'/n):h for n,h in old['source_sha256'].items()})
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained camera build changed')
    output.mkdir(parents=True,exist_ok=False);(output/'source').mkdir();(output/'bin').mkdir()
    for p in (base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/KvCameraPipeline.h').write_bytes(Path(__file__).with_name('KvCameraPipeline.h').read_bytes())
    entry=output/'source/mono_kv260_network.cc';entry.write_text(transform(entry.read_text()))
    compile=list(old['commands'][-2]);compile[compile.index('-c')+1]=str(entry);compile[compile.index('-o')+1]=str(output/'manual_main.o')
    compile=[x.replace(str(base/'source'),str(output/'source')) for x in compile]
    link=list(old['commands'][-1]);link=[str(output/'manual_main.o') if x==str(base/'camera_main.o') else x for x in link]
    link[link.index('-o')+1]=str(output/'bin/mono_kv260_camera')
    state=dict(status='RUNNING',commands=[compile,link],protected_sha256=before,retained_mapping_dso=old['retained_mapping_dso'],
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},manual_control=True,started_monotonic_ns=time.monotonic_ns())
    try:
        with (output/'build.log').open('w') as log:
            for cmd in (compile,link):subprocess.run(cmd,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        exe=output/'bin/mono_kv260_camera';deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps:raise ValueError('Manual camera dependency failure')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained camera products changed')
        state.update(status='NATIVE_CAMERA_ENTRY_BUILD_PASS',dependencies=deps,products_sha256={str(exe):digest(exe)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('root','base','output'):p.add_argument('--'+n,type=Path,required=True)
    run(**vars(p.parse_args()))
