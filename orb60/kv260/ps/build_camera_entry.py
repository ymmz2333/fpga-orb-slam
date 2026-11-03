"""Native camera main with the retained mapping DSO and solver objects unchanged."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import available


def transform(text):
    changes = [
        ('#include "Kv260VideoPipeline.h"', '#include "KvCameraPipeline.h"'),
        ('''    if(argc==4&&std::string(argv[1])=="--verify-video") {
        auto ids=KvNetwork::identities(argv[3]);KvNetwork::VideoSource video(argv[2]);
        for(auto id:ids)KvNetwork::decode(video,id);
        cv::Mat extra;require(!video.read(extra),"Extra unindexed source frames");
        std::cout<<"NATIVE_VIDEO_IDENTITY_PASS frames="<<ids.size()<<std::endl;return 0;
    }
''', ''),
        ('VOCAB YAML VIDEO IDENTITIES ENDPOINT NEW_RUN MAX_FRAMES TELEMETRY(0|1)',
         'VOCAB YAML CAMERA_DEVICE SOURCE_CAMERA_CSV ENDPOINT NEW_RUN MAX_FRAMES TELEMETRY(0|1)'),
        ('const std::string input_format=std::string(argv[3]).compare(0,5,"yuyv:")==0?"YUYV":(std::string(argv[3]).compare(0,5,"uyvy:")==0?"UYVY":"");require(!input_format.empty(),"Explicit packed YUYV/UYVY input required");',
         'const std::string input_format="YUYV";'),
        ('auto ids=KvNetwork::identities(argv[4],limit);',
         'require(limit>0&&limit<=36000,"Finite camera frame count required");KvNetwork::validateCameraCalibration(argv[4],argv[2]);'),
        ('source<<"timestamp_ns,source_frame_index\\n";',
         'source<<"timestamp_ns,source_frame_index\\n";\n    std::ofstream sensor(out+"/camera_frames.csv");sensor<<"source_frame_id,capture_sequence,timestamp_ns,dequeued_ns,sequence_gaps,gray_crc\\n";'),
        ('KvNetwork::VideoPipeline input(argv[3],ids,limit==0);',
         'KvNetwork::CameraPipeline input(argv[3],limit,out+"/camera_profile.json");'),
        ('ids.size()', 'limit'),
        ('source<<f.id.stamp',
         "sensor<<i<<','<<f.sensor.capture_sequence<<','<<f.id.stamp<<','<<f.sensor.dequeued_ns<<','<<f.sensor.sequence_gaps<<','<<f.id.crc<<'\\n';sensor.flush();require(bool(sensor),\"Sensor journal write failed\");\n            source<<f.id.stamp"),
        ('journal.close();source.close();', 'journal.close();source.close();sensor.close();'),
        ('MAPPING_DRAINED_EXPORT_PENDING', 'CAMERA_TRACKING_DRAINED_EXPORT_PENDING'),
        ('\\\"gray_input\\\":\\\"pyav_direct_gray\\\"', '\\\"gray_input\\\":\\\"camera_original_Y\\\"'),
        ('\\\"video_decode_included\\\":true', '\\\"video_decode_included\\\":false,\\\"source_input\\\":\\\"actual_KV260_V4L2_camera\\\"'),
        ('''    slam.Shutdown();slam.ExportBridgeMap(out+"/tracking/map");
    std::ofstream done(out+"/NATIVE_COMPLETE");done<<"Actual 7015 PL, KV260 PS mapping, original video decoded and fully drained\\n";
    std::cout<<"KV260_NETWORK_MAP_COMPLETE"<<std::endl;return 0;''',
         '''    slam.Shutdown();
    std::ofstream camera_done(out+"/CAMERA_INPUT_COMPLETE");camera_done<<"Actual V4L2 input and physical7015 PL drained; inspect map status separately\\n";
    if(!valid){
        atomic_json(out+"/camera_mapping_status.json","{\\"status\\":\\"INPUT_DRAINED_NO_MAP_INITIALIZED\\",\\"mapping_verified\\":false,\\"cpu_orb_calls\\":0}");
        std::cout<<"KV260_CAMERA_INPUT_DRAINED_NO_MAP_INITIALIZED"<<std::endl;return 0;
    }
    slam.ExportBridgeMap(out+"/tracking/map");
    atomic_json(out+"/camera_mapping_status.json","{\\"status\\":\\"CAMERA_MAP_EXPORTED_VALIDATION_PENDING\\",\\"mapping_verified\\":false,\\"cpu_orb_calls\\":0}");
    std::ofstream done(out+"/NATIVE_COMPLETE");done<<"Actual KV260 camera input and7015 PL; map exported, stability validation required\\n";
    std::cout<<"KV260_CAMERA_MAP_EXPORTED"<<std::endl;return 0;'''),
    ]
    output = text
    # ids.size occurs at several reviewed loop/report boundaries; all now refer
    # to the finite sampled-camera frame count. Every other edit is unique.
    for old,new in changes:
        count=output.count(old)
        if (old=='ids.size()' and count!=7) or (old!='ids.size()' and count!=1):
            raise ValueError('Unreviewed camera entry boundary (%d): %s'%(count,old))
        output=output.replace(old,new)
    # Solver call, actual PL identity check and mapper handoff remain exact.
    for line in (
        'auto pose=slam.TrackMonocular(f.gray,double(f.id.stamp)*1e-9);',
        'const double map_sync_ms=mapper_barrier?KvMapperProgress::wait(10000):0;',
        'require(!stats.extractor_calls&&raw.timestamp==f.id.stamp&&raw.count==unsigned(stats.count),"Actual 7015 result identity/CPU ORB violation");'):
        if text.count(line)!=1 or output.count(line)!=1:
            raise ValueError('Camera entry changed an original solver/PL invariant')
    return output


def run(root,base,output):
    root,base,output=map(lambda p:Path(p).resolve(),(root,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:
        raise ValueError('Native KV260 and1536MiB available required')
    old=json.loads((base/'BUILD.json').read_text())
    if old['status']!='NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS':
        raise ValueError('Explicit verified bounded published mapper required')
    before=dict(old['products_sha256'])
    before.update({str(base/'source'/name):h for name,h in old['source_sha256'].items()})
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained mapper changed')
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','bin'):(output/folder).mkdir()
    for p in (base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    authored=Path(__file__).parent
    for source in (authored/'KvCameraPipeline.h',*(authored.parent/'camera'/name for name in ('v4l2_capture.c','v4l2_capture.h','test_capture.c'))):
        (output/'source'/source.name).write_bytes(source.read_bytes())
    entry=output/'source/mono_kv260_network.cc';entry.write_text(transform(entry.read_text()))
    compile=list(old['commands'][0]);compile[compile.index('-c')+1]=str(entry)
    compile[compile.index('-o')+1]=str(output/'camera_main.o')
    compile=[x.replace(str(base/'source'),str(output/'source')) for x in compile]
    link=list(old['link_commands']['executable']);old_object=str(base/'network.o')
    if link.count(old_object)!=1:raise ValueError('Original main link object mismatch')
    link[link.index(old_object)]=str(output/'camera_main.o');link.insert(4,str(output/'camera_capture.o'))
    exe=output/'bin/mono_kv260_camera';link[link.index('-o')+1]=str(exe)
    flags=['cc','-std=c11','-O3','-Wall','-Wextra','-Werror','-Wno-misleading-indentation']
    unit=[*flags,str(output/'source/test_capture.c'),'-o',str(output/'bin/test_capture')]
    driver=[*flags,'-c',str(output/'source/v4l2_capture.c'),'-o',str(output/'camera_capture.o')]
    commands=[unit,[str(output/'bin/test_capture')],driver,compile,link]
    state=dict(status='RUNNING',scope=__doc__,commands=commands,protected_sha256=before,
               started_monotonic_ns=time.monotonic_ns(),retained_mapping_dso=old['products_sha256'],
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()})
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                if available()<1536*1024:raise MemoryError('Compile memory margin fell below1536MiB')
                subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(base/'lib/libORB_SLAM3.so') not in deps:
            raise ValueError('Retained camera mapping runtime dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained mapper changed during build')
        state.update(status='NATIVE_CAMERA_ENTRY_BUILD_PASS',dependencies=deps,products_sha256={str(exe):digest(exe)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:
        state['finished_monotonic_ns']=time.monotonic_ns()
        (output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','base','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
