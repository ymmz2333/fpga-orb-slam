import json,socket
from unittest.mock import Mock
import pytest
from orb60.kv260.peer_link import transport_failure,validate_orphan
from orb60.kv260.tests.test_manual_control import fixture


def orphan():
    return dict(PID='42',START='99',EXE='/opt/orb-demo/kv260_network_camera_manual_test/bin/zynq-demo',
        OUTPUT='/opt/orb-demo/kv260_network_camera_manual_test/runs/network-boot-abc/app',SHA='a'*64,FAULT_SHA='b'*64,DISPLAY='1',
        FAULT=json.dumps(dict(mode='ERROR',error='Bridge socket timeout/disconnected',calibration_sha256='c'*64,cpu_orb_calls=0,hardware_verified=True,hardware_fault=True)))


def test_disconnect_retirement_requires_exact_network_fault_and_drained_renderer():
    assert validate_orphan(orphan(),'a'*64,'c'*64)['error']=='Bridge socket timeout/disconnected'


@pytest.mark.parametrize('case',('hardware_fault','crc','camera','cpu_orb','not_drained','binary','other_owner','pid','escape'))
def test_reconnect_cannot_retire_crc_hardware_or_unrelated_processing(case):
    v=orphan();fault=json.loads(v['FAULT'])
    if case=='hardware_fault':fault['error']='Physical ORB timeout'
    if case=='crc':fault['error']='Network camera pixels CRC mismatch'
    if case=='camera':fault['calibration_sha256']='d'*64
    if case=='cpu_orb':fault['cpu_orb_calls']=1
    if case=='not_drained':v['DISPLAY']='0'
    if case=='binary':v['SHA']='e'*64
    if case=='other_owner':v['EXE']='/opt/other/bin/zynq-demo'
    if case=='pid':v['PID']='42;killall'
    if case=='escape':v['OUTPUT']='/opt/orb-demo/kv260_network_camera_manual_test/runs/network-x/../app'
    v['FAULT']=json.dumps(fault)
    with pytest.raises(ValueError):validate_orphan(v,'a'*64,'c'*64)


def test_only_transport_io_can_be_retried_not_camera_crc_or_native_checks():
    assert transport_failure(ConnectionResetError('link changed'),'SEND_PIXELS')
    assert transport_failure(socket.timeout('peer lost'),'CONNECT_PIXELS')
    assert not transport_failure(ValueError('CRC mismatch'),'SEND_PIXELS')
    assert not transport_failure(OSError('camera unplugged'),'CAPTURE')
    assert not transport_failure(TimeoutError('native ORB hung'),'RECEIVER_START')
    assert not transport_failure(OSError('corrupt evidence'),'VERIFY_DRAINED_RESULT')
    assert not transport_failure(OSError('disk full'),'JOURNAL')


def test_network_exit_preserves_failed_result_and_waits_without_closing_panel(tmp_path):
    s=fixture(tmp_path);s.kind='localization';s.phase='LOCALIZING';s.job.poll.return_value=1
    s.run.mkdir();result=dict(status='FAILED',transport_disconnect=True,error='ConnectionResetError(104)')
    f=s.run/'RESULT.json';f.write_text(json.dumps(result));s.tick()
    assert s.phase=='WAIT_NETWORK' and s.waiting_intent=='localization' and s.job is None and not s.quitting
    assert json.loads(f.read_text())==result


def test_packet_fault_does_not_become_network_wait(tmp_path):
    s=fixture(tmp_path);s.kind='localization';s.phase='LOCALIZING';s.job.poll.return_value=1
    s.run.mkdir();(s.run/'RESULT.json').write_text(json.dumps(dict(status='FAILED',transport_disconnect=False,error='CRC mismatch')))
    s.tick();assert s.phase=='ERROR'


def test_peer_unavailable_queues_operator_mapping_without_starting_process(tmp_path):
    s=fixture(tmp_path);s.job=None;s.phase='IDLE';s.network=Mock();s.network.available.return_value=False
    s.spawn=Mock();s.start_mapping()
    assert s.phase=='WAIT_NETWORK' and s.waiting_intent=='mapping'
    s.spawn.assert_not_called();s.network.prepare.assert_not_called()
    s.action('stop_mapping');assert s.phase=='IDLE' and not s.waiting_intent


def test_wait_network_keeps_latest_map_and_reconnects_only_requested_mode(tmp_path):
    s=fixture(tmp_path);s.job=None;s.phase='WAIT_NETWORK';s.waiting_intent='localization';s.next_network_attempt=0
    s.handoff=tmp_path/'latest';s.start_localization=Mock();s.tick()
    s.start_localization.assert_called_once();assert s.handoff==tmp_path/'latest'


def test_mid_mapping_failure_never_automatically_discards_graph_and_restarts(tmp_path):
    s=fixture(tmp_path);s.job.poll.return_value=1;s.network=Mock();s.network.available.return_value=False
    s.run.mkdir();(s.run/'processing_started.json').write_text('{}');s.tick()
    assert s.phase=='ERROR' and not getattr(s,'waiting_intent',None)
