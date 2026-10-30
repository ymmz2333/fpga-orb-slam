"""Unit test for INCR bursts, byte strobes, and randomized AXI stalls."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

from common.axi_ram import AxiRamModel


async def wait_handshake(clock, valid, ready):
    valid.value = 1
    while True:
        await RisingEdge(clock)
        if int(ready.value):
            break
    await FallingEdge(clock)
    valid.value = 0


@cocotb.test()
async def test_four_beat_incrementing_burst(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    # Initialize master-driven signals before starting the slave model.
    dut.rst.value = 1
    for name in (
        "m_axi_awaddr", "m_axi_awlen", "m_axi_awsize", "m_axi_awburst",
        "m_axi_awvalid", "m_axi_wdata", "m_axi_wstrb", "m_axi_wlast",
        "m_axi_wvalid", "m_axi_bready", "m_axi_araddr", "m_axi_arlen",
        "m_axi_arsize", "m_axi_arburst", "m_axi_arvalid", "m_axi_rready",
    ):
        getattr(dut, name).value = 0

    ram = AxiRamModel(
        dut,
        "m_axi",
        dut.clk,
        dut.rst,
        size=1 << 16,
        stall_probability=0.40,
        read_latency=(0, 4),
        write_response_latency=(0, 4),
        seed=404,
    )
    ram.start()

    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

    address = 0x0200
    words = [0x11223344, 0x55667788, 0xA1B2C3D4, 0x0BADF00D]

    await FallingEdge(dut.clk)
    dut.m_axi_awaddr.value = address
    dut.m_axi_awlen.value = len(words) - 1
    dut.m_axi_awsize.value = 2  # four bytes
    dut.m_axi_awburst.value = 1  # INCR
    await wait_handshake(dut.clk, dut.m_axi_awvalid, dut.m_axi_awready)

    for index, word in enumerate(words):
        dut.m_axi_wdata.value = word
        dut.m_axi_wstrb.value = 0xF
        dut.m_axi_wlast.value = 1 if index == len(words) - 1 else 0
        await wait_handshake(dut.clk, dut.m_axi_wvalid, dut.m_axi_wready)

    dut.m_axi_bready.value = 1
    while True:
        await RisingEdge(dut.clk)
        if int(dut.m_axi_bvalid.value):
            assert int(dut.m_axi_bresp.value) == 0
            break
    await FallingEdge(dut.clk)
    dut.m_axi_bready.value = 0

    expected_bytes = b"".join(word.to_bytes(4, "little") for word in words)
    assert ram.read(address, len(expected_bytes)) == expected_bytes

    dut.m_axi_araddr.value = address
    dut.m_axi_arlen.value = len(words) - 1
    dut.m_axi_arsize.value = 2
    dut.m_axi_arburst.value = 1
    await wait_handshake(dut.clk, dut.m_axi_arvalid, dut.m_axi_arready)

    dut.m_axi_rready.value = 1
    received = []
    while len(received) < len(words):
        await RisingEdge(dut.clk)
        if int(dut.m_axi_rvalid.value):
            assert int(dut.m_axi_rresp.value) == 0
            received.append(int(dut.m_axi_rdata.value))
            assert int(dut.m_axi_rlast.value) == (len(received) == len(words))

    await FallingEdge(dut.clk)
    dut.m_axi_rready.value = 0
    assert received == words

