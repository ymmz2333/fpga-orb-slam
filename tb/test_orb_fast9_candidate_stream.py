"""Exact sparse-list verification for the retained FAST/NMS boundary."""
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

from test_orb_fast9_nms import nms_reference
from test_orb_fast9_stream import fast9_reference


ROOT = Path(__file__).resolve().parents[1]
PANORAMA = ROOT / "panorama"
WIDTH = 160
HEIGHT = 96


async def reset_dut(dut):
    dut.rst.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_candidate_ready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


@cocotb.test()
async def test_sparse_candidates_exact_under_backpressure(dut):
    import cv2
    import numpy as np

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    source = cv2.imread(
        str(PANORAMA / "assets" / "input_720p" / "frame_001.jpg"),
        cv2.IMREAD_GRAYSCALE,
    )
    gray = cv2.resize(source, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    score = fast9_reference(gray)
    keep = nms_reference(score)
    expected = [
        (x, y, int(score[y, x]))
        for y in range(4, HEIGHT - 4)
        for x in range(4, WIDTH - 4)
        if keep[y, x]
    ]

    rng = random.Random(0xFA57)
    source_index = 0
    holding = False
    actual = []
    done = False
    cycles = 0
    pixels = gray.reshape(-1)
    blocked = None
    while not done:
        cycles += 1
        assert cycles < WIDTH * HEIGHT * 6
        await FallingEdge(dut.clk)

        if not holding and source_index < len(pixels) and rng.random() >= 0.10:
            x = source_index % WIDTH
            dut.s_axis_tdata.value = int(pixels[source_index])
            dut.s_axis_tvalid.value = 1
            dut.s_axis_tuser.value = int(source_index == 0)
            dut.s_axis_tlast.value = int(x == WIDTH - 1)
            holding = True
        elif not holding:
            dut.s_axis_tvalid.value = 0

        dut.m_candidate_ready.value = int(rng.random() >= 0.22)
        await Timer(1, unit="ns")

        source_fire = int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value)
        valid = int(dut.m_candidate_valid.value)
        ready = int(dut.m_candidate_ready.value)
        payload = int(dut.m_candidate_data.value) if valid else None
        if blocked is not None:
            assert valid and payload == blocked
        blocked = payload if valid and not ready else None

        await RisingEdge(dut.clk)
        if source_fire:
            source_index += 1
            holding = False
        if valid and ready:
            actual.append((payload & 0xFFFF, (payload >> 16) & 0xFFFF, (payload >> 40) & 0xFF))
        done = bool(int(dut.m_frame_done.value))

    assert source_index == len(pixels)
    assert actual == expected
    assert int(dut.m_candidate_count.value) == len(expected)
    dut._log.info(
        "sparse candidate boundary exact: %d records in %d cycles",
        len(actual), cycles,
    )
