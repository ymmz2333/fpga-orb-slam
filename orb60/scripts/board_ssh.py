"""Run bounded SSH/SCP through WSL OpenSSH, with a UART-pinned host key.

Local credentials live under ignored build/local; never use global known_hosts
or disable host verification. Python 3.8+ and the standard library suffice.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--put", nargs=2, metavar=("LOCAL", "REMOTE"))
    parser.add_argument("--get", nargs=2, metavar=("REMOTE", "LOCAL"))
    parser.add_argument("command", nargs="?")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory(prefix="orb60-ssh-") as tmp:
        known = Path(tmp) / "known_hosts"
        known.write_text("orb60-board " + cfg["host_key"] + "\n")
        common = ["-o", "UserKnownHostsFile=" + str(known),
                  "-o", "StrictHostKeyChecking=yes", "-o", "HostKeyAlias=orb60-board",
                  "-o", "ConnectTimeout=10", "-o", "NumberOfPasswordPrompts=1",
                  "-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]
        target = cfg.get("user", "root") + "@" + cfg["host"]
        if args.put:
            cmd = ["scp"] + common + [args.put[0], target.split("@")[0] + "@[" + cfg["host"] + "]:" + shlex.quote(args.put[1])]
        elif args.get:
            cmd = ["scp"] + common + [target.split("@")[0] + "@[" + cfg["host"] + "]:" + shlex.quote(args.get[0]), args.get[1]]
        else:
            if not args.command:
                parser.error("command or --put/--get is required")
            cmd = ["ssh"] + common + ["-T", target, args.command]
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp(cmd[0], cmd)
        deadline = time.monotonic() + args.timeout
        pending = b""
        sent = False
        output_bytes = 0
        timed_out = False
        try:
            while True:
                if time.monotonic() > deadline:
                    timed_out = True
                    os.kill(pid, signal.SIGTERM)
                    break
                readable, _, _ = select.select([fd], [], [], min(0.25, max(0, deadline-time.monotonic())))
                if readable:
                    try:
                        data = os.read(fd, 65536)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        break
                    if not data:
                        break
                    pending += data
                    if b"password:" in pending.lower():
                        if sent:
                            raise RuntimeError("Authentication rejected; not retrying credentials")
                        os.write(fd, (cfg["password"] + "\n").encode())
                        pending = b""
                        sent = True
                    elif sent or b"password:" not in pending.lower():
                        # Retain a short suffix so a split password prompt is recognized.
                        cut = len(pending) if sent else max(0, len(pending)-128)
                        if cut:
                            sys.stdout.buffer.write(pending[:cut])
                            sys.stdout.buffer.flush()
                            output_bytes += cut
                            pending = pending[cut:]
                    if output_bytes > 2 * 1024 * 1024:
                        raise RuntimeError("SSH output exceeded 2 MiB; request a bounded log")
            if pending:
                sys.stdout.buffer.write(pending)
                sys.stdout.buffer.flush()
        finally:
            os.close(fd)
            _, status = os.waitpid(pid, 0)
        if timed_out:
            print("\nSSH_TIMEOUT: bounded client stopped; inspect remote job state before retrying", file=sys.stderr)
            return 124
        return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 128+os.WTERMSIG(status)


if __name__ == "__main__":
    sys.exit(main())
