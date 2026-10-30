"""Run generated HLS descriptor RTL over every real bookshelf frame.

The randomized single-frame test remains the AXI protocol acceptance gate.
This batch test removes artificial stalls so all fourteen frames can be
processed in one elaboration while still checking every output byte against
the independent Python fixed-point model.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import cocotb
import cv2
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from common.axi_lite import AxiLiteMaster, drive_axi_sidebands
from common.axi_ram import AxiRamModel


ROOT = Path(__file__).resolve().parents[1]
PANORAMA = ROOT / "panorama"
sys.path.insert(0, str(PANORAMA / "hls_orb_list_descriptor"))

from prepare_acceptance import pack_records, select_records  # noqa: E402


WIDTH = 320
HEIGHT = 180
IMAGE_ADDRESS = 0x0010_0000
CANDIDATE_ADDRESS = 0x0020_0000
OUTPUT_ADDRESS = 0x0030_0000
MAX_FEATURES = 512


async def write_pointer(control, address, value):
    await control.write(address, value & 0xFFFF_FFFF)


def unpack_candidates(payload: bytes) -> list[tuple[int, int, int]]:
    assert len(payload) % 8 == 0
    result = []
    for (word,) in struct.iter_unpack("<Q", payload):
        result.append((word & 0xFFFF, (word >> 16) & 0xFFFF, (word >> 40) & 0xFF))
    return result


@cocotb.test()
async def generated_descriptor_processes_all_bookshelf_frames(dut):
    source_dir = PANORAMA / "assets" / "input_720p"
    candidate_dir = PANORAMA / "build" / "pl_fast_batch_320x180"
    output_dir = PANORAMA / "build" / "pl_descriptors_320x180"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(source_dir.glob("frame_*.jpg"))
    assert len(paths) == 14

    cocotb.start_soon(Clock(dut.ap_clk, 10, unit="ns").start())
    drive_axi_sidebands(dut, "m_axi_gmem0")
    drive_axi_sidebands(dut, "m_axi_gmem1")
    input_ram = AxiRamModel(
        dut, "m_axi_gmem0", dut.ap_clk, dut.ap_rst_n,
        size=0x180000, base_address=IMAGE_ADDRESS,
        stall_probability=0.0, read_latency=(0, 0),
        write_response_latency=(0, 0), seed=20260830,
        reset_active_level=0,
    )
    output_ram = AxiRamModel(
        dut, "m_axi_gmem1", dut.ap_clk, dut.ap_rst_n,
        size=0x10000, base_address=OUTPUT_ADDRESS,
        stall_probability=0.0, read_latency=(0, 0),
        write_response_latency=(0, 0), seed=20260831,
        reset_active_level=0,
    )
    input_ram.start()
    output_ram.start()

    control = AxiLiteMaster(dut, "s_axi_control", dut.ap_clk)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 10)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    await write_pointer(control, 0x10, IMAGE_ADDRESS)
    await write_pointer(control, 0x18, CANDIDATE_ADDRESS)
    await write_pointer(control, 0x20, OUTPUT_ADDRESS)
    await control.write(0x28, HEIGHT)
    await control.write(0x30, WIDTH)
    await control.write(0x40, MAX_FEATURES)

    report = []
    for index, path in enumerate(paths, start=1):
        source = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        assert source is not None
        gray = cv2.resize(source, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
        candidate_payload = (
            candidate_dir / f"frame_{index:03d}_candidates.bin"
        ).read_bytes()
        candidates = unpack_candidates(candidate_payload)
        expected = pack_records(select_records(gray, candidates))

        input_ram.write(IMAGE_ADDRESS, gray.tobytes())
        input_ram.write(CANDIDATE_ADDRESS, candidate_payload)
        output_ram.write(OUTPUT_ADDRESS, bytes(0x6000))
        await control.write(0x38, len(candidates))
        await control.write(0x00, 1)

        elapsed = 0
        while elapsed < 1_000_000:
            await ClockCycles(dut.ap_clk, 2000)
            elapsed += 2000
            if await control.read(0x00) & 0x2:
                break
        else:
            raise TimeoutError(f"descriptor RTL timed out on frame {index}")

        count = int.from_bytes(output_ram.read(OUTPUT_ADDRESS, 8), "little")
        actual = output_ram.read(OUTPUT_ADDRESS, 8 + count * 40)
        assert actual == expected, f"descriptor mismatch on frame {index}"
        destination = output_dir / f"frame_{index:03d}_descriptors.bin"
        destination.write_bytes(actual)
        report.append({
            "frame": index,
            "fast_candidates": len(candidates),
            "descriptors": count,
            "completed_by_cycle": elapsed,
            "output": destination.name,
        })
        dut._log.info(
            "frame %02d exact: %d candidates -> %d descriptors, <=%d cycles",
            index, len(candidates), count, elapsed,
        )

    (output_dir / "rtl_descriptor_report.json").write_text(
        json.dumps({
            "status": "pass",
            "source": "generated Vitis HLS RTL in ModelSim",
            "resolution": [WIDTH, HEIGHT],
            "python_byte_exact": True,
            "frames": report,
        }, indent=2),
        encoding="utf-8",
    )
