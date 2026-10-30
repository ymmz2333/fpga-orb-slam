#!/usr/bin/env python3
"""Verify every transferred file SHA-256 using Python 3.8 stdlib on the board."""
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
manifest = json.loads((root / "transfer_manifest.json").read_text())
for relative, expected in manifest["sha256"].items():
    path = (root / relative).resolve()
    if root not in path.parents:
        raise RuntimeError("Unsafe manifest path")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RuntimeError("Transfer SHA256 mismatch: "+relative)
print("A2_TRANSFER_PASS files=%d archive_sha256=%s" % (len(manifest["sha256"]), manifest["archive_sha256"]))
