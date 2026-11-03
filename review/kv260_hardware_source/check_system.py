"""Independent DPU-only full-top gate, adapted from check_unified.py without relaxing static checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("FPGA_PROJECT_ROOT", str(Path(__file__).resolve().parents[3])))
FINGERPRINT = 0x101000016010407


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def bit_fields(data: bytes) -> dict[str, bytes]:
    """Decode the Xilinx .bit envelope; compare configuration bytes, not dates."""
    if len(data) < 13:
        raise ValueError("truncated bitstream header")
    pos = 2 + int.from_bytes(data[:2], "big")
    if data[pos:pos+2] != b"\x00\x01":
        raise ValueError("invalid bitstream tag marker")
    pos += 2
    fields = {}
    for expected in "abcde":
        if pos >= len(data) or chr(data[pos]) != expected:
            raise ValueError("missing bitstream field " + expected)
        pos += 1
        width = 4 if expected == "e" else 2
        if pos + width > len(data):
            raise ValueError("truncated bitstream length")
        size = int.from_bytes(data[pos:pos+width], "big")
        pos += width
        if pos + size > len(data):
            raise ValueError("truncated bitstream field " + expected)
        fields[expected] = data[pos:pos+size]
        pos += size
    if pos != len(data) or not fields["e"]:
        raise ValueError("empty or trailing configuration payload")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    job = args.job.resolve()
    problems: list[str] = []
    summary = {"scope": "complete KV260 DPU + point-project routed top",
               "platform_kind":"dpu_points","board_verified": False}
    names = ["routed.dcp", "utilization.rpt", "utilization_hierarchical.rpt", "congestion.rpt",
             "route_status.rpt", "drc.rpt", "methodology.rpt", "timing_summary.rpt", "setup_paths.rpt",
             "hold_paths.rpt", "clock_interaction.rpt", "cdc.rpt", "check_timing.rpt", "routed_audit.tsv"]
    names += ["dpu_arch.json", "dpu_properties.tsv", "bd_inventory.tsv", "address_map.tsv", "build_config.json", "exceptions_summary.rpt", "kv260_dpu_points.xsa"]
    if args.release:
        names += ["kv260_dpu_points.bit", "kv260_dpu_points.bin", "kv260_dpu_points_with_bit.xsa"]
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
    if (job / "dpu_properties.tsv").exists():
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
    else:
        problems.append("DPU configuration missing")
    if (job / "dpu_arch.json").exists():
        generated = json.loads(read(job / "dpu_arch.json"))
        if int(generated.get("fingerprint", "0"), 16) != FINGERPRINT:
            problems.append("official DPU generated fingerprint mismatch")
    inventory_path = job / "bd_inventory.tsv"
    if inventory_path.exists():
        inventory = [line.split("\t", 1) for line in read(inventory_path).splitlines()]
        dpu_count = sum(v.startswith("xilinx.com:ip:dpuczdx8g:") for _, v in inventory)
        hls_count = sum(":hls:" in v for _, v in inventory)
        summary["structure"] = {"dpu_ip_count": dpu_count, "hls_ip_count": hls_count}
        if dpu_count != 1 or hls_count != 1:
            problems.append("standalone platform must contain exactly one DPU and one point-project HLS IP")
    if inventory_path.exists():
        if sum(v == "xilinx.com:hls:point_project_hls:1.0" for _, v in inventory) != 1:
            problems.append("Unexpected HLS kernel in complete top")
    if (job / "build_config.json").exists():
        config = json.loads((job / "build_config.json").read_text(encoding="utf-8-sig"))
        summary["clocks_mhz"] = {k: config[k] for k in ("control_mhz", "dpu_mhz", "dsp_mhz")}
        if config.get("platform_kind") != "dpu_points" or config["dsp_mhz"] != 2*config["dpu_mhz"]:
            problems.append("invalid DPU-only clock configuration")
        if (job / "routed_audit.tsv").exists():
            clocks = {line.split("\t")[1]: float(line.split("\t")[2])
                      for line in read(job / "routed_audit.tsv").splitlines() if line.startswith("clock\t")}
            for prefix, target in (("clk_out1_", config["control_mhz"]), ("clk_out2_", config["dpu_mhz"]), ("clk_out3_", config["dsp_mhz"])):
                matches = [period for name, period in clocks.items() if name.startswith(prefix)]
                if len(matches) != 1 or abs(1000/matches[0]-target) > target*0.005:
                    problems.append(f"actual routed clock does not match {prefix}{target} MHz")
    # Bind this hardware to the frozen, visually accepted QAT MiDaS model.
    model_dir = ROOT / "orb60/build/kv260_system/depth_midas_qat/compiled"
    try:
        model = model_dir / "midas_kv260_b4096.xmodel"
        model_sha = hashlib.sha256(model.read_bytes()).hexdigest()
        compile_info = json.loads(read(model_dir / "compilation.json"))
        profile = json.loads(read(model_dir / "target_profile.json"))
        if model_sha != compile_info["model_sha256"] or model_sha != "24733de9949579552db3ec42c742c18febab5a4762407318dcef07f9c4b5de09":
            problems.append("frozen MiDaS target model hash mismatch")
        if [int(fp, 16) for fp in profile["fingerprints"]] != [FINGERPRINT]:
            problems.append("model fingerprint does not match standalone hardware")
        summary["model_binding"] = {"path": str(model.relative_to(ROOT)), "sha256": model_sha,
            "fingerprint": hex(FINGERPRINT), "hardware_inference_verified": False,
            "numerical_acceptance": compile_info["numerical_acceptance"],
            "user_visual_acceptance": compile_info["user_visual_acceptance"]}
    except (OSError, KeyError, ValueError) as exc:
        problems.append("model binding incomplete: " + str(exc))
    if args.release and (job / "kv260_dpu_points_with_bit.xsa").exists():
        try:
            with zipfile.ZipFile(job / "kv260_dpu_points_with_bit.xsa") as archive:
                bits = [name for name in archive.namelist() if name.endswith(".bit")]
                if len(bits) != 1:
                    problems.append("XSA must contain exactly one bitstream")
                else:
                    embedded = bit_fields(archive.read(bits[0]))
                    standalone = bit_fields((job / "kv260_dpu_points.bit").read_bytes())
                    if any(embedded[key] != standalone[key] for key in ("a", "b", "e")):
                        problems.append("XSA bitstream configuration differs from standalone bitstream")
                    if standalone["b"].rstrip(b"\x00") != b"xck26-sfvc784-2LV-c":
                        problems.append("exported bitstream has wrong target device")
                    summary["bitstream_configuration_sha256"] = hashlib.sha256(standalone["e"]).hexdigest()
                    summary["xsa_configuration_sha256"] = hashlib.sha256(embedded["e"]).hexdigest()
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            problems.append("XSA bitstream validation failed: " + str(exc))
    provenance = job / "kernel_provenance.json"
    if not provenance.exists():
        problems.append("Kernel source/IP provenance missing")
    else:
        names += ["kernel_provenance.json", "point_abi.json", "source_manifest.json"]
        for relative, expected in json.loads(read(provenance)).items():
            file = ROOT / relative
            if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                problems.append("Tested HLS/IP changed: " + relative)
        for relative, expected in json.loads(read(job / "source_manifest.json")).items():
            if hashlib.sha256((job / relative).read_bytes()).hexdigest() != expected:
                problems.append("Top source snapshot changed: " + relative)
    summary["status"] = "FAILED_OR_INCOMPLETE" if problems else "FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED"
    summary["problems"] = problems
    summary["sha256"] = {name: hashlib.file_digest((job/name).open("rb"), "sha256").hexdigest()
                         for name in names if (job/name).is_file()}
    (job / "validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if not problems:
        (job / "static_pass.stamp").write_text(json.dumps({"routed_sha256": summary["sha256"]["routed.dcp"], "board_verified": False}) + "\n", encoding="utf-8")
    elif (job / "static_pass.stamp").exists():
        (job / "static_pass.stamp").unlink()
    if args.release:
        summary["export_verified"] = not problems
        (job / "release_manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "sha256"}, indent=2))
    raise SystemExit(bool(problems))


if __name__ == "__main__":
    main()
