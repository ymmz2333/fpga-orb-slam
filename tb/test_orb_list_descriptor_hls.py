"""Independent cocotb gate for generated candidate-list descriptor RTL."""
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from common.axi_lite import AxiLiteMaster, drive_axi_sidebands
from common.axi_ram import AxiRamModel


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "panorama" / "hls_orb_list_descriptor" / "build"
WIDTH = 160
HEIGHT = 96
IMAGE_ADDRESS = 0x0010_0000
CANDIDATE_ADDRESS = 0x0020_0000
OUTPUT_ADDRESS = 0x0030_0000


async def write_pointer(control, address, value):
    await control.write(address, value & 0xFFFF_FFFF)


@cocotb.test()
async def generated_list_descriptor_matches_python_golden(dut):
    image = (BUILD / "input_gray.raw").read_bytes()
    candidates = (BUILD / "candidates.bin").read_bytes()
    expected = (BUILD / "expected.bin").read_bytes()
    candidate_count = int((BUILD / "candidate_count.txt").read_text())

    cocotb.start_soon(Clock(dut.ap_clk, 10, unit="ns").start())
    drive_axi_sidebands(dut, "m_axi_gmem0")
    drive_axi_sidebands(dut, "m_axi_gmem1")
    input_ram = AxiRamModel(
        dut, "m_axi_gmem0", dut.ap_clk, dut.ap_rst_n,
        size=0x180000, base_address=IMAGE_ADDRESS,
        stall_probability=0.12, read_latency=(0, 4),
        write_response_latency=(0, 3), seed=20261001,
        reset_active_level=0,
    )
    output_ram = AxiRamModel(
        dut, "m_axi_gmem1", dut.ap_clk, dut.ap_rst_n,
        size=0x10000, base_address=OUTPUT_ADDRESS,
        stall_probability=0.12, read_latency=(0, 4),
        write_response_latency=(0, 4), seed=20261002,
        reset_active_level=0,
    )
    input_ram.write(IMAGE_ADDRESS, image)
    input_ram.write(CANDIDATE_ADDRESS, candidates)
    input_ram.start()
    output_ram.start()

    control = AxiLiteMaster(dut, "s_axi_control", dut.ap_clk)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 10)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    await write_pointer(control, 0x10, IMAGE_ADDRESS)
    await write_pointer(control, 0x18, CANDIDATE_ADDRESS)
    await write_pointer(control, 0x20, OUTPUT_ADDRESS)
    await control.write(0x28, HEIGHT)
    await control.write(0x30, WIDTH)
    await control.write(0x38, candidate_count)
    await control.write(0x40, 128)
    await control.write(0x00, 1)

    elapsed = 0
    while elapsed < 500_000:
        await ClockCycles(dut.ap_clk, 1000)
        elapsed += 1000
        if await control.read(0x00) & 0x2:
            break
    else:
        raise TimeoutError("generated list descriptor RTL timed out")

    count = int.from_bytes(output_ram.read(OUTPUT_ADDRESS, 8), "little")
    actual = output_ram.read(OUTPUT_ADDRESS, 8 + count * 40)
    artifact_dir = ROOT / "panorama" / "build" / "hls_orb_list_cocotb"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "output_rtl.bin").write_bytes(actual)
    (artifact_dir / "report.txt").write_text(
        "status=pass\nrecords={}\nbytes={}\ncompleted_by_cycle={}\n"
        "random_axi_stalls=true\n".format(count, len(actual), elapsed),
        encoding="utf-8",
    )
    assert actual == expected
    assert count == 65
    dut._log.info(
        "generated list descriptor exact: %d records by <=%d cycles",
        count, elapsed,
    )
