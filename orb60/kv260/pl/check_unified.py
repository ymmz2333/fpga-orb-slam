"""Fail closed on missing full-top timing, routing, target or coverage evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FINGERPRINT = 0x101000016010407


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main(kind="orb_dpu") -> None:
    if kind not in ("orb_dpu","orb_only"):raise ValueError('Unknown complete platform kind')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    args = parser.parse_args()
    job = args.job.resolve()
    problems: list[str] = []
    summary = {"scope": "complete KV260 ORB + DPU routed top" if kind=="orb_dpu" else "complete KV260 ORB-only routed top for PS CPU depth",
               "platform_kind":kind,"board_verified": False}
    names = ["routed.dcp", "utilization.rpt", "utilization_hierarchical.rpt", "congestion.rpt",
             "route_status.rpt", "drc.rpt", "methodology.rpt", "timing_summary.rpt", "setup_paths.rpt",
             "hold_paths.rpt", "clock_interaction.rpt", "cdc.rpt", "check_timing.rpt", "routed_audit.tsv"]
    if kind=="orb_dpu":names.append('dpu_arch.json')
    missing = [name for name in names if not (job / name).is_file()]
    if missing:
        problems.append("missing full-top evidence: " + ", ".join(missing))
    if (job / "timing_summary.rpt").exists():
        text = read(job / "timing_summary.rpt")
        m = re.search(r"WNS\(ns\)\s+TNS\(ns\)[^\n]*\n[\s-]+\n\s*((?:[-+]?\d+(?:\.\d+)?\s+){11}[-+]?\d+(?:\.\d+)?)", text)
        if not m:
            problems.append("aggregate timing table missing")
        else:
            values = list(map(float, m[1].split()))
            keys = ["wns_ns", "tns_ns", "setup_failing_endpoints", "setup_endpoints", "whs_ns", "ths_ns",
                    "hold_failing_endpoints", "hold_endpoints", "wpws_ns", "tpws_ns", "pulse_failing_endpoints", "pulse_endpoints"]
            summary["timing"] = dict(zip(keys, values))
            if any(values[i] < 0 for i in (0, 4, 8)) or any(values[i] != 0 for i in (1, 2, 5, 6, 9, 10)):
                problems.append("setup/hold/pulse timing not closed")
    if (job / "check_timing.rpt").exists():
        text = read(job / "check_timing.rpt")
        coverage = {}
        for name, sentence in {
            "no_clock": r"register/latch pins with no clock\.",
            "unconstrained_internal_endpoints": r"pins that are not constrained for maximum delay\.",
            "no_input_delay": r"input ports with no input delay specified\.",
            "no_output_delay": r"ports with no output delay specified\.",
        }.items():
            m = re.search(rf"(?m)^\d+\.\s+checking {name}[^\n]*\n-+\n\s*There are (\d+) {sentence}", text)
            if not m:
                problems.append(f"missing coverage count: {name}")
            else:
                coverage[name] = int(m[1])
                if int(m[1]):
                    problems.append(f"unresolved coverage {name}={m[1]}")
        summary["coverage"] = coverage
    if (job / "route_status.rpt").exists():
        text = read(job / "route_status.rpt")
        counts = {}
        for name, pattern in {"routable": "routable nets", "routed": "fully routed nets", "errors": "nets with routing errors"}.items():
            m = re.search(r"# of " + pattern + r"[. \t]*:\s*(\d+)", text)
            if m:
                counts[name] = int(m[1])
            else:
                problems.append(f"route count absent: {name}")
        summary["routing"] = counts
        if counts.get("routable") != counts.get("routed") or counts.get("errors", -1) != 0:
            problems.append("incomplete or erroneous routing")
    if (job / "routed_audit.tsv").exists():
        facts = {}
        for line in read(job / "routed_audit.tsv").splitlines():
            fields = line.split("\t")
            if fields[0] != "clock":
                facts[fields[0]] = fields[1]
        summary["audit"] = facts
        for name in ("black_box_count", "drc_errors", "drc_critical_warnings"):
            if facts.get(name) != "0":
                problems.append(f"{name} not zero")
        if facts.get("part") != "xck26-sfvc784-2LV-c":
            problems.append("wrong board part")
    if (job / "utilization.rpt").exists():
        resources = {}
        text = read(job / "utilization.rpt")
        for key, label in {"lut": "CLB LUTs", "ff": "CLB Registers", "bram_tiles": "Block RAM Tile", "uram": "URAM", "dsp": "DSPs"}.items():
            m = re.search(r"(?m)^\|\s*" + re.escape(label) + r"\*?\s*\|([^\n]+)", text)
            if not m:
                problems.append(f"missing resource row: {key}")
                continue
            fields = [x.strip() for x in m[1].split("|") if x.strip()]
            resources[key] = {"used": float(fields[0]), "available": float(fields[-2]), "percent": float(fields[-1])}
        summary["resources"] = resources
    if kind=="orb_dpu" and (job / "dpu_properties.tsv").exists():
        props = dict(line.split("\t", 1) for line in read(job / "dpu_properties.tsv").splitlines())
        def val(name: str) -> int:
            return int(float(props["CONFIG." + name]))
        # Same expression as the official fingerprint_json.ttcl; assert generated arch too.
        arch = {(8, 16, 16): 7}.get((val("ARCH_PP"), val("ARCH_ICP"), val("ARCH_OCP")), -1)
        fp = (arch + (val("ALU_PARALLEL") << 8) + ((val("LOAD_PARALLEL").bit_length()-1) << 16)
              + (val("ARCH_IMG_BKGRP") << 24) + (val("LOAD_AUGM") << 26)
              + (val("CONV_LEAKYRELU") << 28) + (val("ALU_LEAKYRELU") << 29)
              + ((val("CONV_WR_PARALLEL").bit_length()-1) << 32)
              + ((val("MISC_WR_PARALLEL").bit_length()-1) << 34) + (1 << 48) + (1 << 56))
        summary["dpu_fingerprint"] = hex(fp)
        if fp != FINGERPRINT:
            problems.append("DPU fingerprint differs from selected compiled model")
    elif kind=="orb_dpu":
        problems.append("DPU configuration missing")
    if kind=="orb_dpu" and (job / "dpu_arch.json").exists():
        generated = json.loads(read(job / "dpu_arch.json"))
        if int(generated.get("fingerprint", "0"), 16) != FINGERPRINT:
            problems.append("official DPU generated fingerprint mismatch")
    summary["status"] = "FAILED_OR_INCOMPLETE" if problems else "FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED"
    summary["problems"] = problems
    summary["sha256"] = {name: hashlib.file_digest((job/name).open("rb"), "sha256").hexdigest()
                         for name in names if (job/name).is_file()}
    (job / "validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "sha256"}, indent=2))
    raise SystemExit(bool(problems))


if __name__ == "__main__":
    main()
