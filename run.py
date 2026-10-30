#!/usr/bin/env python3
"""Run cocotb tests with the simulator selected for each implementation."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RTL = ROOT / "rtl"
TB = ROOT / "tb"
HLS_FAST_RTL = (
    ROOT
    / "panorama"
    / "hls_fast"
    / "vision_fast_prj"
    / "solution1"
    / "syn"
    / "verilog"
)
HLS_ORB_DESCRIPTOR_RTL = (
    ROOT
    / "panorama"
    / "hls_orb_descriptor"
    / "orb_descriptor_prj"
    / "solution1"
    / "syn"
    / "verilog"
)
HLS_ORB_LIST_DESCRIPTOR_RTL = (
    ROOT
    / "panorama"
    / "hls_orb_list_descriptor"
    / "orb_list_descriptor_prj"
    / "solution1"
    / "syn"
    / "verilog"
)
MODELSIM_BIN = Path(os.environ.get("FPGA_MODELSIM_BIN", r"C:\modeltech64_2020.4\win64"))
MODELSIM_LICENSE = Path(
    os.environ.get("FPGA_MODELSIM_LICENSE", str(MODELSIM_BIN / "LICENSE.TXT"))
)
FAST_BATCH_DIR = ROOT / "panorama" / "build" / "pl_fast_batch_320x180"

sys.path.insert(0, str(TB))
os.environ["PYTHONPATH"] = str(TB) + os.pathsep + os.environ.get("PYTHONPATH", "")


def prepare_fast_batch():
    import cv2

    FAST_BATCH_DIR.mkdir(parents=True, exist_ok=True)
    input_dir = ROOT / "panorama" / "assets" / "input_720p"
    paths = sorted(input_dir.glob("frame_*.jpg"))
    if len(paths) != 14:
        raise RuntimeError("expected 14 panorama input frames")
    pixel_path = FAST_BATCH_DIR / "input_pixels.hex"
    with pixel_path.open("w", encoding="ascii", newline="\n") as output:
        for path in paths:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise RuntimeError("cannot read {}".format(path))
            image = cv2.resize(image, (320, 180), interpolation=cv2.INTER_AREA)
            for value in image.reshape(-1):
                output.write("{:02x}\n".format(int(value)))
    os.environ["FAST_BATCH_OUTPUT_DIR"] = str(FAST_BATCH_DIR)

try:
    from cocotb_tools.runner import get_results, get_runner
except ImportError:
    print("cocotb is missing. Install requirements.txt first.")
    raise SystemExit(2)


CASES = {
    "ram": {
        "top": "axi_ram_harness",
        "module": "test_axi_ram_burst",
        "sources": [TB / "axi_ram_harness.v"],
    },
    "axis": {
        "top": "axis_invert",
        "module": "test_axis_invert",
        "sources": [RTL / "axis_invert.v"],
    },
    "dma": {
        "top": "axi_image_invert_dma",
        "module": "test_axi_dma_invert",
        "sources": [RTL / "axi_image_invert_dma.v"],
    },
    "video_framer": {
        "top": "axis_video_framer",
        "module": "test_axis_video_framer",
        "sources": [RTL / "axis_video_framer.v"],
        "parameters": {"WIDTH": 8, "HEIGHT": 4},
    },
    "candidate_packetizer": {
        "top": "orb_candidate_packetizer",
        "module": "test_orb_candidate_packetizer",
        "sources": [RTL / "orb_candidate_packetizer.v"],
        "parameters": {"MAX_CANDIDATES": 4},
    },
    "feature_frontend": {
        "top": "orb_feature_frontend",
        "module": "test_orb_feature_frontend",
        "sources": [
            RTL / "axis_video_framer.v",
            RTL / "orb_fast9_stream.v",
            RTL / "orb_fast9_nms.v",
            RTL / "orb_fast9_nms_pipeline.v",
            RTL / "orb_fast9_candidate_stream.v",
            RTL / "orb_candidate_packetizer.v",
            RTL / "orb_feature_frontend.v",
        ],
        "parameters": {
            "WIDTH": 160, "HEIGHT": 96, "THRESHOLD": 20,
            "MAX_CANDIDATES": 8192,
        },
    },
    "hamming": {
        "top": "orb_hamming_matcher",
        "module": "test_orb_hamming_matcher",
        "sources": [RTL / "orb_hamming_matcher.v"],
    },
    "hamming_axi": {
        "top": "orb_hamming_axi_controller",
        "module": "test_orb_hamming_axi_controller",
        "sources": [
            RTL / "orb_hamming_matcher.v",
            RTL / "orb_hamming_axi_controller.v",
        ],
    },
    "fast9": {
        "top": "orb_fast9_stream",
        "module": "test_orb_fast9_stream",
        "sources": [RTL / "orb_fast9_stream.v"],
        "parameters": {"WIDTH": 160, "HEIGHT": 96, "THRESHOLD": 20},
    },
    "nms": {
        "top": "orb_fast9_nms",
        "module": "test_orb_fast9_nms",
        "sources": [RTL / "orb_fast9_nms.v"],
        "parameters": {"WIDTH": 160, "HEIGHT": 96},
    },
    "fast9_nms_pipeline": {
        "top": "orb_fast9_nms_pipeline",
        "module": "test_orb_fast9_nms_pipeline",
        "sources": [
            RTL / "orb_fast9_stream.v",
            RTL / "orb_fast9_nms.v",
            RTL / "orb_fast9_nms_pipeline.v",
        ],
        "parameters": {"WIDTH": 160, "HEIGHT": 96, "THRESHOLD": 20},
    },
    "fast9_candidates": {
        "top": "orb_fast9_candidate_stream",
        "module": "test_orb_fast9_candidate_stream",
        "sources": [
            RTL / "orb_fast9_stream.v",
            RTL / "orb_fast9_nms.v",
            RTL / "orb_fast9_nms_pipeline.v",
            RTL / "orb_fast9_candidate_stream.v",
        ],
        "parameters": {"WIDTH": 160, "HEIGHT": 96, "THRESHOLD": 20},
    },
    "fast9_batch": {
        "top": "fast_candidate_batch_harness",
        "module": "test_fast_candidate_batch",
        "sources": [
            RTL / "orb_fast9_stream.v",
            RTL / "orb_fast9_nms.v",
            RTL / "orb_fast9_nms_pipeline.v",
            RTL / "orb_fast9_candidate_stream.v",
            TB / "fast_candidate_batch_harness.v",
        ],
        "parameters": {
            "WIDTH": 320, "HEIGHT": 180, "FRAME_COUNT": 14,
            "MAX_CANDIDATES": 8192, "THRESHOLD": 20,
        },
        "prepare": prepare_fast_batch,
        "defines": {
            "INPUT_PIXELS_HEX": FAST_BATCH_DIR / "input_pixels.hex",
            "OUTPUT_CANDIDATES_HEX": FAST_BATCH_DIR / "candidates.hex",
            "OUTPUT_COUNTS_HEX": FAST_BATCH_DIR / "counts.hex",
        },
    },
    "hls_fast": {
        "top": "vision_fast_nms",
        "module": "test_vision_fast_nms_hls",
        "sources": sorted(HLS_FAST_RTL.glob("*.v")),
        # Icarus propagates X through some Vitis HLS generated memories.  Use
        # the licensed ModelSim/Questa-compatible simulator for this netlist.
        "simulator": "questa",
    },
    "hls_orb_descriptor": {
        "top": "orb_descriptor_accel",
        "module": "test_orb_descriptor_hls",
        "sources": sorted(HLS_ORB_DESCRIPTOR_RTL.glob("*.v")),
        # ModelSim 2020.4 still applies the legacy Windows path limit.  One
        # legal HLS-generated module name makes the original absolute path 249
        # characters long, so stage exact copies under build/ before compile.
        "source_stage": ROOT / "build" / "hls_orb_rtl",
        "simulator": "questa",
    },
    "hls_orb_list_descriptor": {
        "top": "orb_list_descriptor_accel",
        "module": "test_orb_list_descriptor_hls",
        "sources": sorted(HLS_ORB_LIST_DESCRIPTOR_RTL.glob("*.v")),
        "source_stage": ROOT / "build" / "hls_orb_list_rtl",
        "simulator": "questa",
    },
    "hls_orb_list_batch": {
        "top": "orb_list_descriptor_accel",
        "module": "test_orb_list_descriptor_batch",
        "sources": sorted(HLS_ORB_LIST_DESCRIPTOR_RTL.glob("*.v")),
        "source_stage": ROOT / "build" / "hls_orb_list_rtl",
        # The randomized acceptance gate above uses ModelSim.  Icarus runs the
        # exact same generated Verilog faster for the fourteen-frame batch.
        "simulator": "icarus",
    },
    "bug_hamming": {
        "top": "orb_hamming_matcher_bad_msb",
        "module": "test_orb_hamming_matcher",
        "sources": [
            RTL / "orb_hamming_matcher.v",
            RTL / "mutants" / "orb_hamming_matcher_bad_msb.v",
        ],
    },
    "bug_math": {
        "top": "axis_invert_off_by_one",
        "module": "test_axis_invert",
        "sources": [RTL / "mutants" / "axis_invert_off_by_one.v"],
    },
    "bug_backpressure": {
        "top": "axis_invert_bad_backpressure",
        "module": "test_axis_invert",
        "sources": [RTL / "mutants" / "axis_invert_bad_backpressure.v"],
    },
}


def configure_simulator(simulator):
    if simulator != "questa":
        return
    if not (MODELSIM_BIN / "vsim.exe").exists():
        raise RuntimeError("ModelSim was not found at {}".format(MODELSIM_BIN))
    if not MODELSIM_LICENSE.exists():
        raise RuntimeError(
            "ModelSim license file was not found at {}".format(MODELSIM_LICENSE)
        )
    os.environ["PATH"] = str(MODELSIM_BIN) + os.pathsep + os.environ["PATH"]
    os.environ["MGLS_LICENSE_FILE"] = str(MODELSIM_LICENSE)
    os.environ["LM_LICENSE_FILE"] = str(MODELSIM_LICENSE)
    # cocotb 2.x uses this compatibility path for older ModelSim SE releases.
    os.environ["COCOTB__QUESTA_MODE"] = "compat"


def convert_fst_to_vcd(build_dir, top):
    fst_path = build_dir / (top + ".fst")
    if not fst_path.exists():
        candidates = sorted(
            build_dir.glob("*.fst"), key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise RuntimeError("waveform conversion requested but no FST was generated")
        fst_path = candidates[0]

    converter = shutil.which("fst2vcd")
    if not converter:
        raise RuntimeError(
            "fst2vcd was not found; install GTKWave or OSS CAD Suite"
        )
    vcd_path = fst_path.with_suffix(".vcd")
    subprocess.run(
        [converter, "-f", str(fst_path), "-o", str(vcd_path)],
        check=True,
    )
    print("VCD waveform: {}".format(vcd_path))


def run_case(name, waves=False, vcd=False):
    case = CASES[name]
    if "prepare" in case:
        case["prepare"]()
    simulator = case.get("simulator", "icarus")
    configure_simulator(simulator)
    if vcd and simulator != "icarus":
        raise RuntimeError(
            "--vcd currently applies only to Icarus cases; use ModelSim WLF "
            "for {}".format(name)
        )
    runner = get_runner(simulator)
    build_dir = ROOT / "build" / "sim" / name
    sources = case["sources"]
    if "source_stage" in case:
        stage = case["source_stage"]
        stage.mkdir(parents=True, exist_ok=True)
        staged_sources = []
        for source in sources:
            destination = stage / source.name
            shutil.copy2(source, destination)
            staged_sources.append(destination)
        sources = staged_sources
    if simulator == "icarus":
        build_args = ["-g2012"]
    elif simulator == "verilator":
        # Vitis HLS emits harmless #0 initialization delays and numerous
        # conservative width warnings in its generated AXI adapters.
        build_args = ["--timing", "-Wno-fatal"]
    else:
        build_args = []
    for define, value in case.get("defines", {}).items():
        build_args.append('-D{}="{}"'.format(define, Path(value).as_posix()))
    runner.build(
        hdl_toplevel=case["top"],
        sources=[str(path) for path in sources],
        build_dir=str(build_dir),
        build_args=build_args,
        parameters=case.get("parameters", {}),
        waves=waves,
        always=True,
    )
    results_file = runner.test(
        hdl_toplevel=case["top"],
        test_module=case["module"],
        build_dir=str(build_dir),
        waves=waves,
    )
    total, failed = get_results(results_file)
    if vcd:
        convert_fst_to_vcd(build_dir, case["top"])
    if total == 0 or failed:
        raise RuntimeError(
            "{}: {} of {} cocotb tests failed".format(name, failed, total)
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", choices=tuple(CASES) + ("all",), default="all"
    )
    parser.add_argument("--waves", action="store_true")
    parser.add_argument(
        "--vcd", action="store_true",
        help="generate waves and convert FST to VCD for VS Code WaveTrace"
    )
    parser.add_argument(
        "--image", help="PNG/JPEG input for the AXI-Stream image test"
    )
    parser.add_argument(
        "--max-dim", type=int, default=256,
        help="resize the image so its longest edge is at most this value"
    )
    args = parser.parse_args()

    if args.image:
        if args.test not in ("all", "axis"):
            parser.error("--image is only valid with --test axis or --test all")
        if args.max_dim < 1:
            parser.error("--max-dim must be positive")
        os.environ["FPGA_IMAGE_PATH"] = str(Path(args.image).resolve())
        os.environ["FPGA_IMAGE_MAX_DIM"] = str(args.max_dim)

    production_cases = [
        "ram", "axis", "dma", "video_framer", "candidate_packetizer",
        "feature_frontend",
        "hamming", "hamming_axi", "fast9", "nms",
        "fast9_nms_pipeline", "fast9_candidates", "hls_fast",
        "hls_orb_descriptor", "hls_orb_list_descriptor"
    ]
    selected = production_cases if args.test == "all" else [args.test]
    for name in selected:
        print("\n=== running {} ===".format(name))
        run_case(name, waves=(args.waves or args.vcd), vcd=args.vcd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
