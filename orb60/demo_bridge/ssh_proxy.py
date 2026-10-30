"""Binary stdio SSH proxy via the pinned Zynq, without changing PC network settings."""
import argparse
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from orb60.demo_bridge.board import open_board


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--via-host',required=True)
    p.add_argument('--target-host',required=True)
    p.add_argument('--target-port',type=int,default=22)
    a=p.parse_args()
    if os.name=='nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
    with open_board(a.config,a.via_host) as client:
        client.get_transport().set_keepalive(15)
        channel=client.get_transport().open_channel('direct-tcpip',(a.target_host,a.target_port),('127.0.0.1',0),timeout=8)
        def send():
            try:
                while True:
                    # Avoid a buffered-stdin lock held by this daemon thread
                    # during interpreter shutdown after a cable disconnect.
                    data=os.read(sys.stdin.fileno(),32768)
                    if not data:break
                    channel.sendall(data)
            except (OSError,EOFError):pass
            finally:
                try:channel.shutdown_write()
                except OSError:pass
        threading.Thread(target=send,daemon=True).start()
        try:
            while True:
                data=channel.recv(32768)
                if not data:break
                sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
        finally:channel.close()


if __name__=='__main__':main()
