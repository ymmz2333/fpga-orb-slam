"""Run an experiment shell script using the existing pinned board SSH helper."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--script", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    config = args.config or root / "build/local/board_router_ssh.json"
    command = "sh -c " + shlex.quote(args.script.read_text())
    return subprocess.run([sys.executable, str(root / "scripts/board_ssh.py"),
                           "--config", str(config), "--timeout", str(args.timeout),
                           command], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
