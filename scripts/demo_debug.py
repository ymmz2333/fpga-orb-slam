#!/usr/bin/env python3
"""Prove which tools do and do not catch two intentional RTL bugs."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "build" / "debug_demos"
REPORTS.mkdir(parents=True, exist_ok=True)


def execute(name, command, env=None):
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    (REPORTS / (name + ".txt")).write_text(
        completed.stdout, encoding="utf-8"
    )
    return completed


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    clean_env = os.environ.copy()
    clean_env.pop("FPGA_IMAGE_PATH", None)
    clean_env.pop("FPGA_IMAGE_MAX_DIM", None)
    results = []

    good = execute(
        "good_cocotb",
        [sys.executable, "run.py", "--test", "axis"],
        env=clean_env,
    )
    results.append((
        good.returncode == 0,
        "正确设计通过 cocotb 随机反压回归",
    ))

    bug_cases = (
        ("bug_math", "Pixel mismatch"),
        ("bug_backpressure", "AXI4-Stream violation"),
        ("bug_hamming", "Hamming edge mismatch"),
    )
    for case_name, expected_marker in bug_cases:
        completed = execute(
            case_name + "_cocotb",
            [sys.executable, "run.py", "--test", case_name, "--vcd"],
            env=clean_env,
        )
        caught = completed.returncode != 0 and expected_marker in completed.stdout
        results.append((
            caught,
            "cocotb 捕获 {}，日志包含 {!r}".format(
                case_name, expected_marker
            ),
        ))

    mutants = (
        ("axis_invert_off_by_one", [
            "rtl/mutants/axis_invert_off_by_one.v",
        ]),
        ("axis_invert_bad_backpressure", [
            "rtl/mutants/axis_invert_bad_backpressure.v",
        ]),
        ("orb_hamming_matcher_bad_msb", [
            "rtl/orb_hamming_matcher.v",
            "rtl/mutants/orb_hamming_matcher_bad_msb.v",
        ]),
    )

    verilator = shutil.which("verilator")
    yosys = shutil.which("yosys")
    for top, sources in mutants:
        if verilator:
            lint = execute(
                top + "_verilator",
                [verilator, "--lint-only", "-Wall", "-Wno-fatal",
                 "--top-module", top] + sources,
            )
            results.append((
                lint.returncode == 0,
                "Verilator 接受 {}：语法/结构检查不能证明功能正确".format(top),
            ))
        if yosys:
            source_text = " ".join(sources)
            synth = execute(
                top + "_yosys",
                [yosys, "-Q", "-p",
                 "read_verilog -sv {}; hierarchy -check -top {}; "
                 "proc; opt; check".format(source_text, top)],
            )
            results.append((
                synth.returncode == 0,
                "Yosys 接受 {}：可综合也不等于算法正确".format(top),
            ))

    lines = ["调试工具故障注入演示", "=" * 32]
    for passed, description in results:
        lines.append("[PASS] " + description if passed else "[FAIL] " + description)
    lines.extend((
        "",
        "结论：功能错误由参考模型和协议监视器发现；Verilator/Yosys负责",
        "规范、结构和可综合性，不能替代功能测试；FST/VCD波形用于定位原因。",
    ))
    summary = "\n".join(lines) + "\n"
    (REPORTS / "SUMMARY.txt").write_text(summary, encoding="utf-8")
    print(summary)
    return 0 if all(item[0] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
