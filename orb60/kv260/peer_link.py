"""PS-only link wait and retirement of an identified disconnected receiver.

No PL reset, firmware load, map reset, or recovery of a hardware/CRC fault.
"""
import json,re,shlex,socket,time
from pathlib import Path
from .run_network_system import load,save,digest


class PeerBusy(RuntimeError):pass


def transport_failure(error,stage):
    return stage in ('CONNECT_PIXELS','SEND_PIXELS','END_PIXELS') and isinstance(error,OSError)


def validate_orphan(fields,expected_sha,camera_sha):
    exe=fields['EXE'];output=fields['OUTPUT'];fault=json.loads(fields['FAULT'])
    if (not re.fullmatch('/opt/orb-demo/kv260_network_camera_manual_[A-Za-z0-9_]+/bin/zynq-demo',exe) or
        not output.startswith(exe.removesuffix('/bin/zynq-demo')+'/runs/network-') or
        not re.fullmatch('/[A-Za-z0-9_./-]+',output) or '..' in Path(output).parts or not output.endswith('/app')):
        raise ValueError('Resource owner is not an identified manual camera receiver')
    if fields['SHA']!=expected_sha or not re.fullmatch('[0-9]+',fields['PID']) or not re.fullmatch('[0-9]+',fields['START']):
        raise ValueError('Receiver executable/PID identity differs')
    if (fault.get('mode')!='ERROR' or fault.get('error')!='Bridge socket timeout/disconnected' or
        fault.get('calibration_sha256')!=camera_sha or fault.get('cpu_orb_calls')!=0 or
        fault.get('hardware_verified') is not True or fields['DISPLAY']!='1'):
        raise ValueError('Resource owner is not a drained network-disconnect fault; no automatic PL recovery')
    if not re.fullmatch('[0-9a-f]{64}',fields['FAULT_SHA']):raise ValueError('Missing immutable disconnect fault identity')
    return fault


class PeerLink:
    def __init__(self,root,connection,folder,camera):
        self.root=Path(root);self.connection=connection;self.folder=Path(folder);self.camera=Path(camera)
        self.interface=connection['host'].rpartition('%')[2] or 'eth0'
        if not re.fullmatch('[A-Za-z0-9_.-]+',self.interface):raise ValueError('Invalid peer interface')
        self.next_probe=0;self.connected=False

    def available(self,force=False):
        now=time.monotonic()
        if not force and now<self.next_probe:return self.connected
        self.next_probe=now+1.5;self.connected=False
        try:
            if not self.carrier_up():return False
            with socket.create_connection((self.connection['host'],22),timeout=.4):pass
            self.connected=True
        except OSError:pass
        return self.connected

    def carrier_up(self):
        try:return Path('/sys/class/net',self.interface,'carrier').read_text().strip()=='1'
        except OSError:return False

    def prepare(self):
        from .two_board_session import Board
        folder=self.folder/('peer_%d'%time.monotonic_ns());folder.mkdir();board=Board(self.root,self.connection,folder)
        probe='''set -eu
if test ! -e /run/orb-demo.lock; then echo FREE; exit 0; fi
n=0
for p in /proc/[0-9]*; do
    exe=$(readlink "$p/exe" 2>/dev/null) || continue
    case "$exe" in /opt/orb-demo/kv260_network_camera_manual_*/bin/zynq-demo) ;; *) continue;; esac
    n=$((n+1))
    echo "PID=${p##*/}"
    echo "EXE=$exe"
    echo "SHA=$(sha256sum "$exe" | cut -d ' ' -f 1)"
    echo "START=$(awk '{print $22}' "$p/stat")"
    output=$(tr '\\000' '\\n' <"$p/cmdline" | awk '$0=="--output"{getline;print;exit}')
    case "$output" in /opt/orb-demo/kv260_network_camera_manual_*/runs/network-*/app) ;; *) exit 65;; esac
    echo "OUTPUT=$output"
    if test -s "$output/display.json"; then echo DISPLAY=1; else echo DISPLAY=0; fi
    test -s "$output/fault.json" || { echo ACTIVE_RECEIVER_NOT_DRAINED; exit 66; }
    echo "FAULT_SHA=$(sha256sum "$output/fault.json" | cut -d ' ' -f 1)"
    printf 'FAULT='; cat "$output/fault.json"; printf '\\n'
done
test "$n" = 1
'''
        try:board.run(probe,'probe',timeout=20)
        except RuntimeError:
            if 'ACTIVE_RECEIVER_NOT_DRAINED' in (folder/'probe.stdout.log').read_text():
                raise PeerBusy('Previous receiver is still draining; no forced termination')
            raise
        text=(folder/'probe.stdout.log').read_text()
        if text.strip()=='FREE':return
        fields=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
        fault=validate_orphan(fields,self.connection['network_localizer_sha256'],digest(self.camera))
        quote=shlex.quote;pid=fields['PID'];exe=quote(fields['EXE']);output=quote(fields['OUTPUT'])
        script=f'''set -eu
test "$(readlink /proc/{pid}/exe)" = {exe}
test "$(awk '{{print $22}}' /proc/{pid}/stat)" = {fields['START']}
test "$(sha256sum {exe} | cut -d ' ' -f 1)" = {fields['SHA']}
test "$(sha256sum {output}/fault.json | cut -d ' ' -f 1)" = {fields['FAULT_SHA']}
kill -TERM {pid}
n=0; while test -e /proc/{pid}; do n=$((n+1)); test "$n" -lt 150; sleep .1; done
n=0; while test -e /run/orb-demo.lock; do n=$((n+1)); test "$n" -lt 50; sleep .1; done
echo DISCONNECTED_RECEIVER_RETIRED_WITHOUT_PL_RESET
'''
        board.run(script,'retire_disconnected',timeout=25)
        save(folder/'RESULT.json',dict(status='IDENTIFIED_NETWORK_DISCONNECT_RECEIVER_RETIRED',
             old_fault=fault,old_fault_sha256=fields['FAULT_SHA'],pid=int(pid),pl_reset=False,map_reset=False))
