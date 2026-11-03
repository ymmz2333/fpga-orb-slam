"""Explicit recorded-frame physical PL samples for localization diagnosis.

No camera/map inference or production fallback. Samples are CRC-bound to the
failed session's real full-video PL journal; original timestamps remain intact.
"""
import argparse,csv,json,zlib
from pathlib import Path
from .two_board_session import Board
from .network_frontend import NetworkFrontend
from .run_network_system import load,rows,save,digest
from .localization_input import SIZE


def run(a):
    root=a.root.resolve();session=a.session.resolve();out=a.output.resolve()
    selected=[int(n) for n in a.indices.split(',')]
    if not 1<=len(selected)<=300 or selected!=sorted(set(selected)) or selected[0]<0 or selected[-1]>=2273:
        raise ValueError('Finite explicit increasing recorded frame indices required')
    mapped=load(session/'mapping_control/RESULT.json')
    if mapped['status']!='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS':raise ValueError('Accepted actual full-video mapping required for diagnosis')
    timing=rows(session/'native_localization/app/timing.part000000.csv')
    if len(timing)!=2273:raise ValueError('Full failed native localization evidence required')
    tracking=rows(session/'mapping/tracking/frames.csv');fixture=a.fixture.resolve();proof=load(fixture/'RESULT.json')
    if proof['status']!='RECORDED_NETWORK_LOCALIZATION_FIXTURE_VERIFIED' or proof['frames']!=2273 or len(tracking)!=2297:
        raise ValueError('Explicit retained recorded fixture and full mapping required')
    if digest(fixture/'camera_orb.csv')!=digest(session/'handoff/map/camera_orb.csv'):
        raise ValueError('Recorded diagnostic camera differs from failed map')
    source=rows(fixture/'frames.csv')
    if digest(fixture/'frames.csv')!=proof['frames.csv_sha256'] or (fixture/'gray8.bin').stat().st_size!=SIZE*2273:
        raise ValueError('Recorded fixture index/layout changed')
    out.mkdir(parents=True,exist_ok=False);board=Board(root,load(a.connection),out);front=None;report=dict(status='RUNNING',input_kind='recorded_diagnostic',camera_input=False,cpu_orb_calls=0,samples=[])
    try:
        board.start_frontend();front=NetworkFrontend('['+board.connection['host']+']:5600')
        with (fixture/'gray8.bin').open('rb') as raw:
            import numpy as np
            for ordinal,i in enumerate(selected):
                raw.seek(i*SIZE);gray=raw.read(SIZE);reference=tracking[i+24]
                if len(gray)!=SIZE or zlib.crc32(gray)!=int(reference['gray_crc']):
                    raise ValueError('Recorded sample does not match the full mapping source offset24')
                stamp=int(source[i]['timestamp_ns']);payload,result=front.run(np.frombuffer(gray,np.uint8).reshape(720,960),ordinal,stamp)
                crc=zlib.crc32(result['records'])
                if crc!=int(reference['record_crc']) or result['count']!=int(reference['count']) or result['count']!=int(timing[i]['features']):
                    raise ValueError('Physical PL sample differs from same-input frozen mapping/localization')
                name='f%04d.payload'%i;(out/name).write_bytes(payload)
                report['samples'].append(dict(recorded_frame_id=i,mapping_frame_id=i+24,timestamp_ns=stamp,
                    mapping_timestamp_ns=int(reference['timestamp_ns']),wire_source_frame_id=ordinal,gray_crc=zlib.crc32(gray),
                    record_crc=crc,count=result['count'],payload=name,payload_sha256=digest(out/name),engine_ns=result['engine_ns']))
        report.update(status='ACTUAL_SAME_INPUT_PHYSICAL_PL_DIAGNOSTIC_SAMPLES_CAPTURED',sampled_frame_crc_verification=True,
                      whole_fixture_sha_rechecked=False,map_version=load(session/'handoff/HANDOFF.json')['map']['version'],
                      calibration_sha256=proof['camera_sha256'],source_sha256=digest(__file__))
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        if front:front.close()
        try:board.stop_frontend()
        except BaseException as error:report.update(status='FAILED',cleanup_error=repr(error));raise
        finally:save(out/'RESULT.json',report)
    print(json.dumps(dict(status=report['status'],samples=len(report['samples']))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('root','session','fixture','connection','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--indices',required=True);run(p.parse_args())
