"""Persistent password-in-stdin SSH session; private known-hosts and bounded job output."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
import paramiko
import getpass
import shlex
import socket
import threading
import select
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[2]


def apt_proxy(transport, port):
    """Temporary loopback-only Ubuntu mirror proxy, removed with this SSH session."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            parsed=urllib.parse.urlsplit(self.path)
            if parsed.scheme!='http' or not parsed.hostname or not (parsed.hostname=='ports.ubuntu.com' or parsed.hostname.endswith('.ubuntu.com')):
                self.send_error(403,'Only Ubuntu package mirrors are allowed');return
            try:
                req=urllib.request.Request(self.path,headers={'User-Agent':'orb60-kv260-apt-proxy'})
                with urllib.request.urlopen(req,timeout=60) as response:
                    self.send_response(response.status)
                    for name in ('Content-Length','Content-Type','Last-Modified'):
                        if response.headers.get(name):self.send_header(name,response.headers[name])
                    self.end_headers()
                    while data:=response.read(262144):self.wfile.write(data)
            except Exception as error:
                self.send_error(getattr(error,'code',502),str(error))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def forward(channel, origin, destination):
        def run():
            with socket.create_connection(server.server_address) as sock:
                try:
                    while True:
                        ready,_,_=select.select([sock,channel],[],[],30)
                        for source in ready:
                            data=source.recv(65536)
                            if not data:return
                            (channel if source is sock else sock).sendall(data)
                finally:channel.close()
        threading.Thread(target=run,daemon=True).start()
    transport.request_port_forward('127.0.0.1',port,handler=forward)
    return server


def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--user',default='ubuntu')
    p.add_argument('--accept-new',action='store_true')
    p.add_argument('--identity',type=Path,help='Optional ignored local SSH private key')
    p.add_argument('--command-file',type=Path,help='Run one UTF-8 shell script in foreground and wait for its real exit')
    p.add_argument('--sudo-enabled',action='store_true',help='Keep supplied credential in RAM for explicit sudo_exec requests')
    p.add_argument('--apt-proxy-port',type=int)
    p.add_argument('--timeout',type=float,default=8,help='Connection/banner timeout; allow a bounded longer wait during native compilation')
    a=p.parse_args()
    known=ROOT/'orb60/build/local/kv260_known_hosts';known.parent.mkdir(parents=True,exist_ok=True)
    client=paramiko.SSHClient()
    if known.exists():client.load_host_keys(str(known))
    class PinNew(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self,ssh,hostname,key):
            if not a.accept_new:raise RuntimeError('Unpinned KV260 host key')
            ssh.get_host_keys().add(hostname,key.get_name(),key);ssh.save_host_keys(str(known))
            emit({'event':'HOST_KEY_PINNED','host':hostname,'type':key.get_name(),'sha256':hashlib.sha256(key.asbytes()).hexdigest()})
    client.set_missing_host_key_policy(PinNew())
    password=None
    if not a.identity or a.sudo_enabled:
        emit({'event':'PASSWORD_STDIN_READY'})
        password=getpass.getpass('KV260 password: ') if sys.stdin.isatty() else sys.stdin.readline().rstrip('\r\n')
        if not password:raise RuntimeError('No password received on stdin; authentication was not attempted')
    try:client.connect(a.host,username=a.user,password=password,key_filename=str(a.identity) if a.identity else None,look_for_keys=False,allow_agent=False,timeout=a.timeout,auth_timeout=a.timeout,banner_timeout=a.timeout)
    finally:
        if not a.sudo_enabled:password=None
    client.get_transport().set_keepalive(20);emit({'event':'CONNECTED','host':a.host,'user':a.user})
    proxy=apt_proxy(client.get_transport(),a.apt_proxy_port) if a.apt_proxy_port else None
    if proxy:emit({'event':'APT_PROXY_READY','remote_loopback_port':a.apt_proxy_port})
    channel=None;record=None;log=None
    def collect(seconds=1):
        nonlocal channel,record,log
        if channel is None:raise ValueError('No active job')
        deadline=time.monotonic()+min(float(seconds),30);chunk=bytearray()
        while True:
            if not client.get_transport().is_active():
                record.update(status='LOST',error='SSH transport lost; remote completion is unknown')
                channel.close();channel=None;log.close();log=None;break
            for ready,read in [(channel.recv_ready,channel.recv),(channel.recv_stderr_ready,channel.recv_stderr)]:
                while ready():
                    data=read(32768);log.write(data);log.flush();chunk.extend(data)
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                code=channel.recv_exit_status()
                if code==-1:record.update(status='LOST',exit_code=None,error='No trustworthy remote exit status')
                else:record.update(status='SUCCEEDED' if code==0 else 'FAILED',exit_code=code)
                channel.close();channel=None;log.close();log=None;break
            if time.monotonic()>=deadline:record.update(status='RUNNING');break
            time.sleep(.1)
        Path(record['state_file']).write_text(json.dumps(record,indent=2))
        emit({**record,'output_tail':chunk.decode(errors='replace')[-6000:]})
    try:
        requests=[json.dumps({'action':'exec','command':a.command_file.read_text(encoding='utf-8'),'seconds':15})] if a.command_file else sys.stdin
        for line in requests:
            try:
                request=json.loads(line);action=request['action']
                if action in {'exec','sudo_exec'}:
                    if channel is not None:raise RuntimeError('Poll the current foreground job; do not relaunch it')
                    job=f'{time.time_ns()}_{uuid.uuid4().hex[:12]}';folder=ROOT/'orb60/build/kv260_system/ssh_jobs'/job;folder.mkdir(parents=True)
                    record={'job':job,'status':'STARTING','state_file':str(folder/'state.json'),'log':str(folder/'output.log')}
                    log=(folder/'output.log').open('wb');channel=client.get_transport().open_session()
                    command=request['command']
                    if action=='sudo_exec':
                        if not a.sudo_enabled or not password:raise RuntimeError('sudo is not enabled for this session')
                        command="sudo -S -p '' -- sh -c "+shlex.quote(command)
                    channel.exec_command(command)
                    if action=='sudo_exec':channel.sendall((password+'\n').encode())
                    collect(request.get('seconds',10))
                    if a.command_file:
                        while channel is not None:collect(15)
                elif action=='poll':collect(request.get('seconds',10))
                elif action in {'put','get'}:
                    if channel is not None:raise RuntimeError('Wait for foreground command before transferring')
                    with client.open_sftp() as sftp:
                        if action=='put':sftp.put(request['local'],request['remote'])
                        else:sftp.get(request['remote'],request['local'])
                    emit({'status':'TRANSFER_COMPLETE','action':action})
                elif action=='close':break
                else:raise ValueError('Unknown session action')
            except Exception as e:emit({'status':'REQUEST_FAILED','error':repr(e)})
    finally:
        if channel is not None:channel.close()
        if log is not None:log.close()
        if proxy:proxy.shutdown()
        client.close()
        password=None
    if a.command_file and (not record or record.get('status')!='SUCCEEDED'):
        raise SystemExit((record.get('exit_code') or 1) if record else 1)

if __name__=='__main__':main()
