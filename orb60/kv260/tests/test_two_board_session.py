"""Control/archive/report rejection gates; fixtures are not hardware evidence."""
import csv
import io
import json
from pathlib import Path
import tarfile
import pytest
from orb60.kv260.two_board_session import check_configuration, extract_evidence, verify_localization, verify_current_platform, digest


@pytest.mark.parametrize('kind',('ok','reboot','old_dpu','old_point','receipt_changed'))
def test_reboot_or_changed_receipt_refuses_stale_preflight_before_pl_access(tmp_path,kind):
    boot=tmp_path/'boot';boot.write_text('current-boot\n')
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps(dict(status='DPU_POINTS_LOADED',boot_id='current-boot',memory_backend='native-dpu',point_uio='/dev/uio4',bitstream_sha256='fixture-only')))
    point=tmp_path/'point.json';point.write_text(json.dumps(dict(status='DPU_POINTS_BOARD_PREFLIGHT_PASS',boot_id='current-boot',deployment_receipt_sha256=digest(receipt),bitstream_sha256='fixture-only')))
    dpu=tmp_path/'dpu.json';dpu.write_text(json.dumps(dict(status='PROFILE_MATCH',driver='vivado',boot_id='current-boot')))
    cfg=dict(point_preflight=str(point),preflight=str(dpu),point_uio='/dev/uio4');conn=dict(kv_deployment_receipt=str(receipt))
    if kind=='reboot':boot.write_text('another-boot\n')
    elif kind=='old_dpu':dpu.write_text(json.dumps(dict(status='PROFILE_MATCH',driver='vivado')))
    elif kind=='old_point':point.write_text(json.dumps(dict(status='DPU_POINTS_BOARD_PREFLIGHT_PASS')))
    elif kind=='receipt_changed':receipt.write_text(receipt.read_text()+' ')
    if kind=='ok':assert verify_current_platform(tmp_path,cfg,conn,boot)['boot_id']=='current-boot'
    else:
        with pytest.raises(ValueError):verify_current_platform(tmp_path,cfg,conn,boot)


def test_actual_command_line_dispatches_full_and_component_modes(monkeypatch):
    from orb60.kv260 import two_board_session
    calls=[]
    monkeypatch.setattr(two_board_session,'run',lambda **kw:calls.append(kw) or 0)
    args=['--config','mapping.json','--connection','peer.json','--output','fresh-run']
    assert two_board_session.main(args)==0
    assert calls[-1]==dict(config_path=Path('mapping.json'),connection_path=Path('peer.json'),output=Path('fresh-run'),resume_mapping=None)
    assert two_board_session.main(args+['--resume-mapping','accepted-map'])==0
    assert calls[-1]['resume_mapping']==Path('accepted-map')


def connection():
    return json.loads((Path(__file__).parents[1]/'config/two_board_connection.example.json').read_text())


def config():
    return dict(decoder_mode='uncompressed',uncompressed_transport='file',point_backend='pl',
                point_memory_backend='native-dpu',mapper_wait_mode='published',motion_pose_policy='original',
                profile=False,depth_interval_ns=1000000000,acceptance_profile='stable_map_5fps',
                gpu_only=True,local_ba_neighbors=10,endpoint='['+connection()['host']+']:5600')


@pytest.mark.parametrize('value',(0,1,'1','true',None))
def test_matching_selection_is_not_coerced_from_non_boolean_values(value):
    peer=connection();peer['fixed_map_multiview']=value
    with pytest.raises(ValueError,match='boolean'):check_configuration(config(),peer)
    for explicit in (False,True):
        peer['fixed_map_multiview']=explicit;check_configuration(config(),peer)


@pytest.mark.parametrize('change',({'uncompressed_transport':'emulated_stream'},{'point_backend':'cpu'},
    {'point_memory_backend':'xrt'},{'depth_interval_ns':3000000000},{'profile':True},
    {'mapper_wait_mode':'none'},{'motion_pose_policy':'defer-strong'},{'endpoint':'127.0.0.1:5600'},
    {'acceptance_profile':'throughput30'}))
def test_refuses_substituted_compute_and_input(change):
    cfg=config();check_configuration(cfg,connection());cfg.update(change)
    with pytest.raises(ValueError):check_configuration(cfg,connection())


@pytest.mark.parametrize('value',('/opt/orb-demo/x;false','/opt/orb-demo/../x','/tmp/old-release'))
def test_remote_release_scope(value):
    c=connection();c['localization_template']=value
    with pytest.raises(ValueError):check_configuration(config(),c)


@pytest.mark.parametrize('kind',('parent','absolute','symlink','oversized','duplicate'))
def test_archive_rejects_escape_links_capacity_and_duplicate_files(tmp_path,kind):
    archive=tmp_path/'reports.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        item=tarfile.TarInfo({'parent':'../escape','absolute':'/escape'}.get(kind,'file'))
        data=b'fixture'
        if kind=='symlink':item.type=tarfile.SYMTYPE;item.linkname='../escape'
        elif kind=='oversized':item.size=17*1024*1024;data=bytes(item.size)
        else:item.size=len(data)
        tar.addfile(item,None if kind=='symlink' else io.BytesIO(data))
        if kind=='duplicate':tar.addfile(item,io.BytesIO(data))
    with pytest.raises((ValueError,FileExistsError)):extract_evidence(archive,tmp_path/'out')
    assert not (tmp_path/'escape').exists()


def test_archive_allows_native_tar_root_directory(tmp_path):
    archive=tmp_path/'native.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        directory=tarfile.TarInfo('.');directory.type=tarfile.DIRTYPE;tar.addfile(directory)
        item=tarfile.TarInfo('./run/exit_code');item.size=2;tar.addfile(item,io.BytesIO(b'0\n'))
    extract_evidence(archive,tmp_path/'out')
    assert (tmp_path/'out/run/exit_code').read_text()=='0\n'


def write_rows(path,rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def fixture(root):
    (root/'app').mkdir();version='a'*64
    rows=[]
    for i in range(3):
        row=dict(frame_id=i,timestamp_ns=1000000001+i,map_version=version,pose_valid=1)
        row.update({k:0.0 for k in ['tx','ty','tz','r00','r01','r02','r10','r11','r12','r20','r21','r22']});rows.append(row)
    write_rows(root/'app/poses.part000000.csv',rows)
    write_rows(root/'app/timing.part000000.csv',[{k:r[k] for k in ['frame_id','timestamp_ns','map_version','pose_valid']} for r in rows])
    write_rows(root/'app/render.part000000.csv',[dict(frame_id=i,background_builds=int(i==0),background_hits=int(i!=0)) for i in range(3)])
    write_rows(root/'input_index.csv',[dict(frame_index=i,timestamp_ns=1000000001+i) for i in range(3)])
    (root/'exit_code').write_text('0\n');(root/'monotonic_bounds.txt').write_text('20 20.1\n')
    for name in ['map_before.txt','map_after.txt']:(root/name).write_text(version+'\n'+'b'*64+'\n')
    (root/'app/status.json').write_text(json.dumps(dict(hardware_verified=True,hardware_fault=False,cpu_orb_calls=0)))
    (root/'app/display.json').write_text(json.dumps(dict(submitted=3,underruns=0,axi_errors=0)))
    return version


@pytest.mark.parametrize('kind',('ok','time','map','frame','cpu','nan','background','display','fixed_map','missing_row'))
def test_native_report_requires_identity_physical_backend_and_fixed_background(tmp_path,kind):
    version=fixture(tmp_path)
    if kind in ('time','map','frame','nan','missing_row'):
        p=tmp_path/'app/poses.part000000.csv';rows=list(csv.DictReader(p.open()))
        if kind=='time':rows[1]['timestamp_ns']='wrong'
        elif kind=='map':rows[1]['map_version']='c'*64
        elif kind=='frame':rows[1]['frame_id']='2'
        elif kind=='nan':rows[1]['tx']='nan'
        else:rows.pop()
        write_rows(p,rows)
    elif kind=='cpu':(tmp_path/'app/status.json').write_text(json.dumps(dict(hardware_verified=True,cpu_orb_calls=1)))
    elif kind=='background':write_rows(tmp_path/'app/render.part000000.csv',[dict(frame_id=i,background_builds=1,background_hits=0) for i in range(3)])
    elif kind=='display':(tmp_path/'app/display.json').write_text(json.dumps(dict(submitted=2,underruns=0,axi_errors=0)))
    elif kind=='fixed_map':(tmp_path/'map_after.txt').write_text('different')
    if kind=='ok':assert verify_localization(tmp_path,version,3)['frames']==3
    else:
        with pytest.raises(ValueError):verify_localization(tmp_path,version,3)
