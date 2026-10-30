"""AXI4-Stream image test with source gaps and sink backpressure."""
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, with_timeout

from common.axis import AxisSink, AxisSource
from common.image_io import invert_reference, make_test_pattern, write_pgm


ROOT = Path(__file__).resolve().parents[1]


def load_input_image(artifact_dir):
    image_path = os.environ.get("FPGA_IMAGE_PATH")
    if not image_path:
        width = 16
        height = 12
        return width, height, make_test_pattern(width, height), False

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for --image; install requirements.txt"
        ) from exc

    max_dim = int(os.environ.get("FPGA_IMAGE_MAX_DIM", "256"))
    if max_dim < 1:
        raise ValueError("FPGA_IMAGE_MAX_DIM must be positive")

    with Image.open(image_path) as opened:
        rgba = opened.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        rgb = Image.alpha_composite(white, rgba).convert("RGB")

    if max(rgb.size) > max_dim:
        scale = float(max_dim) / max(rgb.size)
        resized = tuple(max(1, int(round(value * scale))) for value in rgb.size)
        rgb = rgb.resize(resized, Image.Resampling.LANCZOS)

    gray = rgb.convert("L")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rgb.save(artifact_dir / "user_input_resized.png")
    gray.save(artifact_dir / "user_input_gray.png")
    return gray.width, gray.height, gray.tobytes(), True


def assert_pixels_equal(actual, expected, width):
    if actual == expected:
        return
    limit = min(len(actual), len(expected))
    for index in range(limit):
        if actual[index] != expected[index]:
            raise AssertionError(
                "Pixel mismatch at index {} (x={}, y={}): expected {}, got {}"
                .format(index, index % width, index // width,
                        expected[index], actual[index])
            )
    raise AssertionError(
        "Pixel count mismatch: expected {}, got {}"
        .format(len(expected), len(actual))
    )


@cocotb.test()
async def test_axis_image_with_backpressure(dut):
    artifact_dir = ROOT / "build" / "artifacts"
    width, height, source_pixels, is_user_image = load_input_image(artifact_dir)
    expected = invert_reference(source_pixels)
    dut._log.info("Embedded Python runtime: %s", sys.version.split()[0])

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.s_axis_tvalid.value = 0
    dut.m_axis_tready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

    source = AxisSource(dut, "s_axis", dut.clk, seed=101)
    sink = AxisSink(dut, "m_axis", dut.clk, seed=202)

    sink_task = cocotb.start_soon(
        sink.recv(len(source_pixels), backpressure_probability=0.30)
    )
    await source.send(source_pixels, width, gap_probability=0.20)
    timeout_ns = max(200_000, len(source_pixels) * 1000)
    output, users, lasts = await with_timeout(sink_task, timeout_ns, "ns")

    assert_pixels_equal(output, expected, width)
    assert users[0] == 1 and sum(users) == 1
    expected_lasts = [1 if (index % width) == width - 1 else 0
                      for index in range(len(source_pixels))]
    assert lasts == expected_lasts

    write_pgm(artifact_dir / "axis_input.pgm", width, height, source_pixels)
    write_pgm(artifact_dir / "axis_output.pgm", width, height, output)

    if is_user_image:
        from PIL import Image
        Image.frombytes("L", (width, height), expected).save(
            artifact_dir / "user_expected.png"
        )
        Image.frombytes("L", (width, height), output).save(
            artifact_dir / "user_rtl_output.png"
        )
        dut._log.info(
            "Processed user image through RTL: %dx%d pixels", width, height
        )
