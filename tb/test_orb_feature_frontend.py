"""End-to-end DMA-packet to FAST candidate-packet verification."""
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

from test_orb_fast9_nms import nms_reference
from test_orb_fast9_stream import fast9_reference


ROOT = Path(__file__).resolve().parents[1]
WIDTH = 160
HEIGHT = 96


@cocotb.test()
async def test_dma_packet_to_terminal_candidate_packet(dut):
    import cv2

    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    dut.aresetn.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_axis_tready.value = 0
    await ClockCycles(dut.aclk, 6)
    dut.aresetn.value = 1
    await ClockCycles(dut.aclk, 2)

    source = cv2.imread(
        str(ROOT / "panorama" / "assets" / "input_720p" / "frame_001.jpg"),
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

    pixels = gray.reshape(-1)
    source_index = 0
    holding = False
    records = []
    rng = random.Random(0xDDAA5511)
    cycles = 0
    terminal = None
    while terminal is None:
        cycles += 1
        assert cycles < WIDTH * HEIGHT * 8
        await FallingEdge(dut.aclk)
        if not holding and source_index < len(pixels) and rng.random() >= 0.08:
            dut.s_axis_tdata.value = int(pixels[source_index])
            dut.s_axis_tvalid.value = 1
            # DMA exposes one packet for the entire image, not one per row.
            dut.s_axis_tlast.value = int(source_index == len(pixels) - 1)
            holding = True
        elif not holding:
            dut.s_axis_tvalid.value = 0
        dut.m_axis_tready.value = int(rng.random() >= 0.20)
        await Timer(1, unit="ns")
        source_fire = int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value)
        output_fire = int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value)
        payload = int(dut.m_axis_tdata.value) if output_fire else 0
        is_last = int(dut.m_axis_tlast.value) if output_fire else 0
        await RisingEdge(dut.aclk)
        if source_fire:
            source_index += 1
            holding = False
        if output_fire:
            assert int(dut.m_axis_tkeep.value) == 0xFF
            if is_last:
                terminal = payload
            else:
                records.append(
                    (payload & 0xFFFF, (payload >> 16) & 0xFFFF,
                     (payload >> 40) & 0xFF)
                )

    assert source_index == len(pixels)
    assert records == expected
    assert (terminal >> 48) == 0xFFFF
    assert (terminal & 0xFFFFFFFF) == len(expected)
    assert ((terminal >> 40) & 0xFF) == 0
    assert int(dut.frame_error.value) == 0
    dut._log.info(
        "integrated front end exact: %d pixels -> %d candidates in %d cycles",
        len(pixels), len(records), cycles,
    )
