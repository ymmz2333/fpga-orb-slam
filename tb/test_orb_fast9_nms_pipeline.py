"""End-to-end cocotb verification for the RTL FAST-9 + NMS candidate."""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

from test_orb_fast9_stream import fast9_reference
from test_orb_fast9_nms import nms_reference


ROOT = Path(__file__).resolve().parents[1]
PANORAMA = ROOT / "panorama"
ARTIFACTS = PANORAMA / "build" / "fast_comparison"
WIDTH = 160
HEIGHT = 96
THRESHOLD = 20


async def reset_dut(dut):
    dut.rst.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_ready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def drive_frame(dut, gray, expected_count, randomized, seed=20260830):
    rng = random.Random(seed)
    pixels = gray.reshape(-1)
    source_index = 0
    holding = False
    outputs = []
    blocked_payload = None
    cycles = 0

    while len(outputs) < expected_count:
        cycles += 1
        assert cycles < len(pixels) * 6, (
            f"timeout after {cycles} cycles: {len(outputs)}/{expected_count}"
        )
        await FallingEdge(dut.clk)

        source_gap = randomized and rng.random() < 0.12
        if not holding and source_index < len(pixels) and not source_gap:
            x = source_index % WIDTH
            dut.s_axis_tdata.value = int(pixels[source_index])
            dut.s_axis_tuser.value = int(source_index == 0)
            dut.s_axis_tlast.value = int(x == WIDTH - 1)
            dut.s_axis_tvalid.value = 1
            holding = True
        elif not holding:
            dut.s_axis_tvalid.value = 0
            dut.s_axis_tuser.value = 0
            dut.s_axis_tlast.value = 0

        dut.m_ready.value = int(not randomized or rng.random() >= 0.18)
        await Timer(1, unit="ns")

        source_fire = bool(
            int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value)
        )
        sink_valid = bool(int(dut.m_valid.value))
        sink_ready = bool(int(dut.m_ready.value))
        payload = None
        if sink_valid:
            payload = (
                int(dut.m_x.value), int(dut.m_y.value),
                int(dut.m_score.value), int(dut.m_keep.value),
                int(dut.m_sof.value), int(dut.m_eol.value),
            )

        if blocked_payload is not None:
            assert sink_valid, "m_valid dropped while blocked"
            assert payload == blocked_payload, "pipeline payload changed while blocked"
        blocked_payload = payload if sink_valid and not sink_ready else None

        await RisingEdge(dut.clk)
        if source_fire:
            source_index += 1
            holding = False
        if sink_valid and sink_ready:
            outputs.append(payload)

    assert source_index == len(pixels)
    return outputs, cycles


def check_outputs(outputs, score, expected_keep):
    for index, (x, y, value, keep, sof, eol) in enumerate(outputs):
        expected_x = 4 + index % (WIDTH - 8)
        expected_y = 4 + index // (WIDTH - 8)
        assert (x, y) == (expected_x, expected_y)
        assert value == int(score[y, x])
        assert keep == int(expected_keep[y, x])
        assert sof == int((x, y) == (4, 4))
        assert eol == int(x == WIDTH - 5)


@cocotb.test()
async def test_integrated_pipeline_exact_with_backpressure(dut):
    import cv2
    import numpy as np

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    input_path = PANORAMA / "assets" / "input_720p" / "frame_001.jpg"
    image = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    gray = cv2.resize(image, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    score = fast9_reference(gray)
    expected_keep = nms_reference(score)
    expected_count = (WIDTH - 8) * (HEIGHT - 8)

    await reset_dut(dut)
    outputs, stalled_cycles = await drive_frame(
        dut, gray, expected_count, randomized=True
    )
    check_outputs(outputs, score, expected_keep)

    # A second reset/run without artificial gaps gives an observed cycle count
    # for the one-pixel-per-cycle architecture, separate from HLS estimates.
    await reset_dut(dut)
    outputs_no_stall, no_stall_cycles = await drive_frame(
        dut, gray, expected_count, randomized=False
    )
    check_outputs(outputs_no_stall, score, expected_keep)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "pass",
        "candidate": "hand_rtl_fast9_nms",
        "resolution": [WIDTH, HEIGHT],
        "input_pixels": int(WIDTH * HEIGHT),
        "dense_outputs_checked_per_run": expected_count,
        "post_nms_keypoints": int(np.count_nonzero(expected_keep)),
        "random_backpressure_cycles": stalled_cycles,
        "no_stall_cycles": no_stall_cycles,
        "no_stall_cycles_per_input_pixel": no_stall_cycles / (WIDTH * HEIGHT),
        "score_or_nms_mismatches": 0,
    }
    (ARTIFACTS / "hand_rtl_cocotb.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dut._log.info(
        "RTL FAST+NMS exact; no-stall=%d cycles, stalled=%d cycles, points=%d",
        no_stall_cycles, stalled_cycles, report["post_nms_keypoints"]
    )
