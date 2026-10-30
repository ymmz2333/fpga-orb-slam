"""Shared-DDR test for the AXI controller around the Hamming pipeline."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from common.axi_lite import AxiLiteMaster
from common.axi_ram import AxiRamModel


QUERY_BASE = 0x1000
TRAIN_BASE = 0x1FE8  # deliberately crosses a 4 KiB boundary
RESULT_BASE = 0x5000


def record(metadata, descriptor):
    return int(metadata).to_bytes(8, "little") + int(descriptor).to_bytes(32, "little")


def distance(left, right):
    return (int(left) ^ int(right)).bit_count()


def expected_match(query, trains):
    ranked = sorted(
        ((distance(query, item), index) for index, item in enumerate(trains)),
        key=lambda item: (item[0], item[1]),
    )
    if not ranked:
        return 0, 0x1FF, 0, 0x1FF, 0
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else (0x1FF, 0)
    return best[1], best[0], second[1], second[0], 1


def decode_result(value):
    return (
        value & 0xFFFF,
        (value >> 16) & 0x1FF,
        (value >> 25) & 0xFFFF,
        (value >> 41) & 0x1FF,
        (value >> 50) & 1,
    )


async def reset_dut(dut):
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def wait_done(control, clock, limit=200000):
    for cycle in range(limit):
        if cycle % 20 == 0:
            status = await control.read(0x04)
            if status & 0x2:
                return status, cycle
        else:
            await RisingEdge(clock)
    raise TimeoutError("Hamming AXI controller timed out")


@cocotb.test()
async def test_axi_hamming_exact_with_bursts_and_empty_train(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    ram = AxiRamModel(
        dut, "m_axi", dut.clk, dut.rst,
        size=0x10000, stall_probability=0.22,
        read_latency=(0, 4), write_response_latency=(0, 3), seed=0x48414D,
    )
    ram.start()
    control = AxiLiteMaster(dut, "s_axi_control", dut.clk)

    rng = random.Random(0xA81)
    queries = [rng.getrandbits(256) for _ in range(3)]
    trains = [rng.getrandbits(256) for _ in range(7)]
    ram.write(QUERY_BASE, b"".join(record(index, value) for index, value in enumerate(queries)))
    ram.write(TRAIN_BASE, b"".join(record(index, value) for index, value in enumerate(trains)))

    await control.write(0x08, QUERY_BASE)
    await control.write(0x0C, TRAIN_BASE)
    await control.write(0x10, RESULT_BASE)
    await control.write(0x14, len(queries))
    await control.write(0x18, len(trains))
    await control.write(0x00, 1)
    status, cycles = await wait_done(control, dut.clk)
    assert status & 0x1 == 0
    assert status & 0xC == 0

    actual = [
        decode_result(int.from_bytes(ram.read(RESULT_BASE + index * 8, 8), "little"))
        for index in range(len(queries))
    ]
    expected = [expected_match(query, trains) for query in queries]
    assert actual == expected
    dut._log.info("AXI Hamming exact for %d comparisons in %d cycles", len(queries) * len(trains), cycles)

    # The same controller must restart without a global reset and produce an
    # explicit invalid result for an empty training list.
    await control.write(0x14, 1)
    await control.write(0x18, 0)
    await control.write(0x00, 1)
    status, _ = await wait_done(control, dut.clk)
    assert status & 0xC == 0
    value = int.from_bytes(ram.read(RESULT_BASE, 8), "little")
    assert decode_result(value) == expected_match(queries[0], [])
