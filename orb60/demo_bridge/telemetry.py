"""Bounded display-only relay, scoped to a single current mapping session."""
from pathlib import Path
import socket
import threading
import time


class Relay:
    def __init__(self, directory, port):
        self.directory = Path(directory)
        self.stop = threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', port))
        self.sock.listen(2)
        self.sock.settimeout(.2)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.clients = []

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                peer, _ = self.sock.accept()
                peer.settimeout(.2)
                worker = threading.Thread(target=self.client, args=(peer,), daemon=True)
                if len(self.clients) >= 2:
                    peer.close()
                    continue
                self.clients.append(peer)
                worker.start()
            except socket.timeout:
                pass
            except OSError:
                break

    def client(self, peer):
        previous = None
        try:
            while not self.stop.is_set():
                path = self.directory / 'latest.orbv'
                try:
                    stamp = path.stat().st_mtime_ns
                    if stamp != previous:
                        packet = path.read_bytes()
                        peer.sendall(packet)
                        previous = stamp
                except FileNotFoundError:
                    pass
                self.stop.wait(.01)
        except OSError:
            pass
        finally:
            peer.close()
            if peer in self.clients:
                self.clients.remove(peer)

    def close(self):
        self.stop.set()
        self.sock.close()
        for peer in list(self.clients):
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.thread.join(timeout=1)
