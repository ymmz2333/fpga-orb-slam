"""Select edge register APIs for native AArch64 VAI 2.5 builds.

The upstream FindXrt.cmake assumes every native build is a PCIe host.  KV260
builds natively too, and uses IS_EDGE=ON.  Honor that explicit platform choice.
"""
import hashlib
import json
from pathlib import Path
import sys

ORIGINAL = "644987b33289b3144149fc83835517f28a198379eea61dbb87bfdd98df6e3453"
BEFORE = "if(CMAKE_CROSSCOMPILING)\n  set(XRT_EDGE_FOUND true)"
AFTER = "if(CMAKE_CROSSCOMPILING OR IS_EDGE)\n  set(XRT_EDGE_FOUND true)"


def main():
    path = Path(sys.argv[1]) / "src/Vitis-AI-Library/cmake/FindXrt.cmake"
    current = path.read_text()
    original = current.replace(AFTER, BEFORE, 1) if AFTER in current else current
    if hashlib.sha256(original.encode()).hexdigest() != ORIGINAL or original.count(BEFORE) != 1:
        raise ValueError("Unexpected upstream XRT finder")
    patched = original.replace(BEFORE, AFTER, 1)
    if current != patched:
        path.write_text(patched)
    record = {"status": "EDGE_XRT_BUILD_SELECTION_PATCHED", "before_sha256": ORIGINAL,
              "after_sha256": hashlib.sha256(patched.encode()).hexdigest(),
              "scope": "CMake platform selection only; native KV260 must use xclRegRead/xclRegWrite, not PCIe xclRead/xclWrite"}
    Path(sys.argv[2]).write_text(json.dumps(record, indent=2) + "\n")
    print(record["status"])


if __name__ == "__main__":
    main()
