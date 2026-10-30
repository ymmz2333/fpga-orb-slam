"""DMA test using a randomized AXI RAM in place of DDR."""
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from common.axi_ram import AxiRamModel
from common.image_io import invert_reference, make_test_pattern, write_pgm


ROOT = Path(__file__).resolve().parents[1]


@cocotb.test()
async def test_dma_image_through_simulated_ddr(dut):
    width = 16
    height = 12
    source_pixels = make_test_pattern(width, height)
    expected = invert_reference(source_pixels)
    source_address = 0x1000
    destination_address = 0x4000

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.start.value = 0
    dut.src_addr.value = 0
    dut.dst_addr.value = 0
    dut.byte_count.value = 0

    ram = AxiRamModel(
        dut,
        "m_axi",
        dut.clk,
        dut.rst,
        size=1 << 18,
        stall_probability=0.35,
        read_latency=(0, 5),
        write_response_latency=(0, 5),
        seed=303,
    )
    ram.start()
    ram.write(source_address, source_pixels)

    await ClockCycles(dut.clk, 6)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

    dut.src_addr.value = source_address
    dut.dst_addr.value = destination_address
    dut.byte_count.value = len(source_pixels)
    dut.start.value = 1
    await ClockCycles(dut.clk, 1)
    dut.start.value = 0

    for _ in range(20000):
        await ClockCycles(dut.clk, 1)
        if int(dut.done.value):
            break
    else:
        raise AssertionError("DMA timeout")

    assert int(dut.error.value) == 0
    assert int(dut.busy.value) == 0
    output = ram.read(destination_address, len(source_pixels))
    assert output == expected

    artifact_dir = ROOT / "build" / "artifacts"
    write_pgm(artifact_dir / "dma_input.pgm", width, height, source_pixels)
    write_pgm(artifact_dir / "dma_output.pgm", width, height, output)

