"""Native pinned-key SSH/SFTP for the Zynq; credentials remain in ignored local config."""
import argparse
import base64
import json
from pathlib import Path
import sys
import paramiko

ROOT=Path(__file__).resolve().parents[2]


def open_board(config, host=None):
    cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
    target=host or cfg['host']
    fields=cfg['host_key'].split()
    key=paramiko.PKey.from_type_string(fields[0],base64.b64decode(fields[1]))
    client=paramiko.SSHClient()
    port=cfg.get('port',22)
    identity=target if port==22 else f'[{target}]:{port}'
    client.get_host_keys().add(identity,key.get_name(),key)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(target,port=cfg.get('port',22),username=cfg.get('user','root'),password=cfg['password'],
                   allow_agent=False,look_for_keys=False,timeout=8,auth_timeout=8,banner_timeout=8)
    return client


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,default=ROOT/'orb60/build/local/board_router_ssh.json')
    p.add_argument('--host')
    p.add_argument('--timeout',type=int,default=30)
    p.add_argument('--pty',action='store_true',help='Line-buffered target diagnostic output')
    p.add_argument('--put',nargs=2)
    p.add_argument('--get',nargs=2)
    p.add_argument('command',nargs='?')
    a=p.parse_args()
    with open_board(a.config,a.host) as client:
        if a.put or a.get:
            with client.open_sftp() as sftp:
                if a.put:sftp.put(*a.put)
                else:sftp.get(*a.get)
            print('SFTP_COMPLETED')
            return 0
        if not a.command:p.error('command or --put/--get required')
        _,stdout,stderr=client.exec_command('PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; '+a.command,timeout=a.timeout,get_pty=a.pty)
        out=stdout.read(65537);err=stderr.read(65537)
        if len(out)>65536 or len(err)>65536:raise RuntimeError('Request bounded remote output')
        sys.stdout.write(out.decode(errors='replace'));sys.stderr.write(err.decode(errors='replace'))
        return stdout.channel.recv_exit_status()


if __name__=='__main__':raise SystemExit(main())
