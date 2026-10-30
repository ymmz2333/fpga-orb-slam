"""Protocol and framing tests for the raw-DMA to video-stream adapter."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer


WIDTH = 8
HEIGHT = 4


async def reset_dut(dut):
    dut.rst.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_axis_tready.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def send_frame(dut, values, rng, bad_last_index=None):
    sent = 0
    holding = False
    outputs = []
    done_error = None
    blocked = None
    while done_error is None:
        await FallingEdge(dut.clk)
        if not holding and sent < len(values) and rng.random() > 0.18:
            dut.s_axis_tdata.value = values[sent]
            dut.s_axis_tvalid.value = 1
            expected_last = sent == len(values) - 1
            if bad_last_index is None:
                dut.s_axis_tlast.value = int(expected_last)
            else:
                dut.s_axis_tlast.value = int(sent == bad_last_index)
            holding = True
        elif not holding:
            dut.s_axis_tvalid.value = 0
            dut.s_axis_tlast.value = 0
        dut.m_axis_tready.value = int(rng.random() > 0.22)
        await Timer(1, unit="ns")

        valid = int(dut.m_axis_tvalid.value)
        ready = int(dut.m_axis_tready.value)
        payload = (
            int(dut.m_axis_tdata.value),
            int(dut.m_axis_tuser.value),
            int(dut.m_axis_tlast.value),
        ) if valid else None
        if blocked is not None:
            assert valid and payload == blocked
        blocked = payload if valid and not ready else None
        source_fire = int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value)

        await RisingEdge(dut.clk)
        if valid and ready:
            outputs.append(payload)
        if source_fire:
            sent += 1
            holding = False
        if int(dut.frame_done.value):
            done_error = int(dut.frame_error.value)

    return outputs, done_error


@cocotb.test()
async def test_video_framing_and_error_detection(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    rng = random.Random(0xF24A)
    values = list(range(WIDTH * HEIGHT))

    outputs, error = await send_frame(dut, values, rng)
    assert error == 0
    assert [item[0] for item in outputs] == values
    assert [index for index, item in enumerate(outputs) if item[1]] == [0]
    assert [index for index, item in enumerate(outputs) if item[2]] == [
        WIDTH - 1, 2 * WIDTH - 1, 3 * WIDTH - 1, 4 * WIDTH - 1
    ]

    outputs, error = await send_frame(dut, values, rng, bad_last_index=7)
    assert len(outputs) == len(values)
    assert error == 1


