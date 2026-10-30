"""Independent cocotb acceptance test for generated ORB descriptor RTL."""
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from common.axi_lite import AxiLiteMaster, drive_axi_sidebands
from common.axi_ram import AxiRamModel


ROOT = Path(__file__).resolve().parents[1]
FAST_BUILD = ROOT / "panorama" / "hls_fast" / "build"
ORB_BUILD = ROOT / "panorama" / "hls_orb_descriptor" / "build"

WIDTH = 160
HEIGHT = 96
CELL_SIZE = 16
MAX_FEATURES = 64
FRAME_BYTES = WIDTH * HEIGHT
IMAGE_ADDRESS = 0x0010_0000
FAST_ADDRESS = 0x0020_0000
OUTPUT_ADDRESS = 0x0030_0000


async def write_pointer(control, low_address, value):
    await control.write(low_address, value & 0xFFFF_FFFF)
    await control.write(low_address + 4, value >> 32)


@cocotb.test()
async def generated_orb_descriptor_matches_independent_golden(dut):
    image = (FAST_BUILD / "input_gray_160x96.raw").read_bytes()
    fast_map = (FAST_BUILD / "fast_output_csim.raw").read_bytes()
    expected = (ORB_BUILD / "orb_output_csim.bin").read_bytes()
    assert len(image) == FRAME_BYTES
    assert len(fast_map) == FRAME_BYTES

    cocotb.start_soon(Clock(dut.ap_clk, 10, unit="ns").start())
    drive_axi_sidebands(dut, "m_axi_gmem0")
    drive_axi_sidebands(dut, "m_axi_gmem1")

    shared_input = AxiRamModel(
        dut, "m_axi_gmem0", dut.ap_clk, dut.ap_rst_n,
        size=0x180000, base_address=IMAGE_ADDRESS,
        stall_probability=0.12, read_latency=(0, 4),
        write_response_latency=(0, 3), seed=20260831,
        reset_active_level=0,
    )
    output_ram = AxiRamModel(
        dut, "m_axi_gmem1", dut.ap_clk, dut.ap_rst_n,
        size=0x10000, base_address=OUTPUT_ADDRESS,
        stall_probability=0.12, read_latency=(0, 4),
        write_response_latency=(0, 4), seed=20260901,
        reset_active_level=0,
    )
    shared_input.write(IMAGE_ADDRESS, image)
    shared_input.write(FAST_ADDRESS, fast_map)
    shared_input.start()
    output_ram.start()

    control = AxiLiteMaster(dut, "s_axi_control", dut.ap_clk)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 10)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    await write_pointer(control, 0x10, IMAGE_ADDRESS)
    await write_pointer(control, 0x1C, FAST_ADDRESS)
    await write_pointer(control, 0x28, OUTPUT_ADDRESS)
    await control.write(0x34, HEIGHT)
    await control.write(0x3C, WIDTH)
    await control.write(0x44, CELL_SIZE)
    await control.write(0x4C, MAX_FEATURES)
    await control.write(0x00, 1)

    elapsed_cycles = 0
    status = 0
    while elapsed_cycles < 350_000:
        await ClockCycles(dut.ap_clk, 1000)
        elapsed_cycles += 1000
        status = await control.read(0x00)
        if status & 0x2:
            break
    else:
        raise TimeoutError(
            "ORB descriptor RTL timed out after {} cycles, status=0x{:08x}".format(
                elapsed_cycles, status
            )
        )

    count = int.from_bytes(output_ram.read(OUTPUT_ADDRESS, 8), "little")
    actual = output_ram.read(OUTPUT_ADDRESS, 8 + count * 40)
    artifact_dir = ROOT / "panorama" / "build" / "hls_orb_descriptor_cocotb"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "orb_output_rtl.bin").write_bytes(actual)
    (artifact_dir / "report.txt").write_text(
        "simulator=cocotb+generated RTL\n"
        "records={}\nbytes={}\ncompleted_by_cycle={}\nrandom_axi_stalls=true\n".format(
            count, len(actual), elapsed_cycles
        ),
        encoding="utf-8",
    )
    assert actual == expected, "generated descriptor RTL differs from CSim/Python golden"
    assert count == 41
    dut._log.info(
        "ORB descriptor RTL PASS: %d records, %d exact bytes, <=%d cycles",
        count, len(actual), elapsed_cycles,
    )
