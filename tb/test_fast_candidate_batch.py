"""Run all prepared frames through actual FAST/NMS/candidate RTL."""
import json
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


OUTPUT_DIR = Path(os.environ["FAST_BATCH_OUTPUT_DIR"])
FRAME_COUNT = 14
MAX_CANDIDATES = 8192


def read_memh(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="ascii").splitlines() if line.strip() and not line.startswith("//")]


@cocotb.test()
async def test_batch_rtl_candidates(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.start.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    for _ in range(1_000_000):
        if int(dut.batch_done.value):
            break
        await RisingEdge(dut.clk)
    else:
        raise AssertionError("batch FAST/NMS RTL timed out")

    count_lines = read_memh(OUTPUT_DIR / "counts.hex")
    counts = [int(value, 16) for value in count_lines[:FRAME_COUNT]]
    candidate_lines = read_memh(OUTPUT_DIR / "candidates.hex")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for frame, count in enumerate(counts):
        assert 0 < count <= MAX_CANDIDATES
        start = frame * MAX_CANDIDATES
        records = []
        output = bytearray()
        for text in candidate_lines[start : start + count]:
            assert "x" not in text.lower()
            value = int(text, 16)
            x = value & 0xFFFF
            y = (value >> 16) & 0xFFFF
            score = (value >> 40) & 0xFF
            assert 4 <= x < 316 and 4 <= y < 176 and score > 20
            records.append({"x": x, "y": y, "score": score})
            output.extend(value.to_bytes(8, "little"))
        (OUTPUT_DIR / f"frame_{frame + 1:03d}_candidates.bin").write_bytes(output)
        frames.append({"frame": frame + 1, "candidate_count": count})

    report = {
        "status": "pass",
        "meaning": "all candidate records were produced by simulated hand RTL",
        "resolution": [320, 180],
        "frames": frames,
        "total_candidates": sum(counts),
    }
    (OUTPUT_DIR / "rtl_candidate_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    dut._log.info("RTL batch produced %d candidates", sum(counts))
