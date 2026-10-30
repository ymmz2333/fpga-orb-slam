"""Bounded candidate packet tests including empty and overflow frames."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer


MAX_CANDIDATES = 4


async def reset_dut(dut):
    dut.rst.value = 1
    dut.s_candidate_data.value = 0
    dut.s_candidate_valid.value = 0
    dut.s_frame_done.value = 0
    dut.s_frame_error.value = 0
    dut.m_axis_tready.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def run_packet(dut, records, frame_error, rng):
    source = 0
    holding = False
    outputs = []
    blocked = None
    done_sent = False
    while True:
        await FallingEdge(dut.clk)
        dut.s_frame_done.value = 0
        dut.s_frame_error.value = frame_error
        if not holding and source < len(records) and rng.random() > 0.12:
            dut.s_candidate_data.value = records[source]
            dut.s_candidate_valid.value = 1
            holding = True
        elif not holding:
            dut.s_candidate_valid.value = 0

        # Frame completion can coincide with the final candidate transfer.
        if source == len(records) and not holding and not done_sent:
            dut.s_frame_done.value = 1
            done_sent = True

        dut.m_axis_tready.value = int(rng.random() > 0.28)
        await Timer(1, unit="ns")
        valid = int(dut.m_axis_tvalid.value)
        ready = int(dut.m_axis_tready.value)
        payload = (
            int(dut.m_axis_tdata.value),
            int(dut.m_axis_tkeep.value),
            int(dut.m_axis_tlast.value),
        ) if valid else None
        if blocked is not None:
            assert valid and payload == blocked
        blocked = payload if valid and not ready else None
        source_fire = int(dut.s_candidate_valid.value) and int(dut.s_candidate_ready.value)

        await RisingEdge(dut.clk)
        if source_fire:
            source += 1
            holding = False
        if valid and ready:
            outputs.append(payload)
        if int(dut.packet_done.value):
            break
    return outputs


@cocotb.test()
async def test_packets_hold_and_bound_candidates(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    rng = random.Random(0xCA7D)

    records = [0x100 + index for index in range(6)]
    outputs = await run_packet(dut, records, 0, rng)
    assert [value for value, _, last in outputs[:-1]] == records[:MAX_CANDIDATES]
    assert all(keep == 0xFF and last == 0 for _, keep, last in outputs[:-1])
    terminal, keep, last = outputs[-1]
    assert keep == 0xFF and last == 1
    assert (terminal >> 48) == 0xFFFF
    assert (terminal & 0xFFFFFFFF) == MAX_CANDIDATES
    assert ((terminal >> 40) & 1) == 1  # overflow

    outputs = await run_packet(dut, [], 1, rng)
    assert len(outputs) == 1
    terminal, keep, last = outputs[0]
    assert last == 1 and keep == 0xFF
    assert (terminal & 0xFFFFFFFF) == 0
    assert ((terminal >> 41) & 1) == 1  # frame error
