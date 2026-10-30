"""Capture actual reboot/startup evidence via pinned SSH; never starts hardware."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from orb60.demo_bridge.board import open_board
from orb60.demo_bridge.protocol import Kind, Packet, receive


class ChannelReader:
    def __init__(self, channel):
        self.channel = channel

    def recv_into(self, buffer):
        data = self.channel.recv(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--before', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    with open_board(a.config) as board:
        def run(command):
            _, out, err = board.exec_command(command, timeout=20)
            stdout = out.read().decode()
            stderr = err.read().decode()
            code = out.channel.recv_exit_status()
            if code:
                raise RuntimeError(f'Board check failed ({code}): {stderr} {stdout}')
            return stdout.strip()

        boot = run('cat /proc/sys/kernel/random/boot_id')
        if boot == a.before:
            raise RuntimeError('Boot ID has not changed')
        run('sh /etc/init.d/orb-demo status')
        binary = run('sha256sum /opt/orb-demo/current/bin/zynq-demo').split()[0]
        if binary != '513716173ca48f7a4cb8b6243f9d036188d790aaa387b8f86706d569246d5ce1':
            raise RuntimeError('Unexpected PS executable')
        run('test -c /dev/video0 && test "$(cat /sys/class/uio/uio0/version)" = wc1')
        run('test ! -e /etc/rc5.d/S99zynq-slam && test -L /etc/rc5.d/S99orb-demo')
        run('sha256sum -c /opt/orb-demo/acceptance/autostart-' + a.before + '/firmware.before.sha256')
        with board.get_transport().open_channel('direct-tcpip', ('127.0.0.1', 5602), ('127.0.0.1', 0)) as sock:
            sock.settimeout(10)
            sock.sendall(Packet(Kind.CONTROL, body=b'status').encode())
            response = receive(ChannelReader(sock))
            if response.kind != Kind.STATUS:
                raise RuntimeError('Invalid PS status reply')
            state = json.loads(response.body)
        if state['mode'] != 'LOCAL' or not state['hardware_verified'] or state['hardware_fault'] or state['cpu_orb_calls']:
            raise RuntimeError(f'Camera/PL/local startup failed: {state}')
        if state['map_version'] != 'ef7dfa4dbf0254ab759ad810d130b3dfa7a073e778a4df349b6930317926873e':
            raise RuntimeError('Unexpected current map')
        log_path = run('readlink /proc/$(pidof zynq-demo)/fd/1')
        banner = run('head -1 ' + log_path)
        if banner != 'DEMO_INPUT=CAMERA DENSE_ENVIRONMENT_POINTS=86461 CPU_ORB=0':
            raise RuntimeError('Dense live-camera startup banner missing')
        pose_file = log_path.rsplit('/', 1)[0] + '/app/poses.part000000.csv'
        poses = run('head -1 ' + pose_file + '; tail -3 ' + pose_file)
        report = dict(client_utc=datetime.now(timezone.utc).isoformat(), status='PASS',
                      boot_id_before=a.before, boot_id_after=boot,
                      binary_sha256=binary, zynq=state, startup_banner=banner,
                      pose_tail=poses, log=log_path, firmware_unchanged=True,
                      old_recording_autostart_disabled=True,
                      scope='Actual SD reboot, USB camera, PL verified, local map and dense RGB load; physical screen confirmation is separate')
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
