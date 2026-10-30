#!/usr/bin/env python3
"""Run simulation, lint, and early synthesis quality gates."""
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "build" / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


DESIGNS = {
    "axis_invert": ["rtl/axis_invert.v"],
    "axi_image_invert_dma": ["rtl/axi_image_invert_dma.v"],
    "orb_hamming_matcher": ["rtl/orb_hamming_matcher.v"],
}


def run(command, report=None):
    print("+ " + " ".join(str(item) for item in command))
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    if report:
        Path(report).write_text(completed.stdout, encoding="utf-8")
    print(completed.stdout)
    if completed.returncode:
        raise RuntimeError("command failed with exit code {}".format(completed.returncode))


def main():
    run([sys.executable, "run.py", "--test", "all"])

    verilator = shutil.which("verilator")
    if verilator:
        for top, sources in DESIGNS.items():
            run(
                [verilator, "--lint-only", "-Wall", "-Wno-fatal",
                 "--top-module", top] + sources,
                REPORTS / (top + "_verilator.txt"),
            )
    else:
        print("[skip] Verilator not found")

    yosys = shutil.which("yosys")
    if yosys:
        for top, sources in DESIGNS.items():
            source_text = " ".join(sources)
            script = (
                "read_verilog -sv {sources}; "
                "hierarchy -check -top {top}; "
                "proc; opt; memory; opt; flatten; techmap; opt; "
                "abc -lut 6; clean; stat -tech xilinx; ltp -noff"
            ).format(sources=source_text, top=top)
            run(
                [yosys, "-Q", "-p", script],
                REPORTS / (top + "_yosys.txt"),
            )
    else:
        print("[skip] Yosys not found")

    print("All available checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
