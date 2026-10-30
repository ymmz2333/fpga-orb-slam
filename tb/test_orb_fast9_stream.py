"""Pixel-exact cocotb verification for the streaming FAST-9 core."""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer


ROOT = Path(__file__).resolve().parents[1]
PANORAMA = ROOT / "panorama"
ARTIFACTS = PANORAMA / "build" / "rtl_orb"
WIDTH = 160
HEIGHT = 96
THRESHOLD = 20


FAST_CIRCLE = (
    (0, -3), (1, -3), (2, -2), (3, -1),
    (3, 0), (3, 1), (2, 2), (1, 3),
    (0, 3), (-1, 3), (-2, 2), (-3, 1),
    (-3, 0), (-3, -1), (-2, -2), (-1, -3),
)


def fast9_reference(gray):
    """Return the exact score definition implemented by the RTL."""
    import numpy as np

    score = np.zeros(gray.shape, dtype=np.uint8)
    for y in range(3, gray.shape[0] - 3):
        for x in range(3, gray.shape[1] - 3):
            center = int(gray[y, x])
            ring = [int(gray[y + dy, x + dx]) for dx, dy in FAST_CIRCLE]
            best = 0
            for start in range(16):
                bright = 255
                dark = 255
                for offset in range(9):
                    value = ring[(start + offset) & 15]
                    bright = min(bright, max(0, value - center))
                    dark = min(dark, max(0, center - value))
                best = max(best, bright, dark)
            score[y, x] = best
    return score


async def reset_dut(dut):
    dut.rst.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tuser.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_ready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def stream_frame_with_stalls(dut, gray, expected_count, seed=90210):
    """Drive a frame and collect outputs while exercising both handshakes."""
    rng = random.Random(seed)
    pixels = gray.reshape(-1)
    source_index = 0
    holding = False
    outputs = []
    blocked_payload = None
    cycle_count = 0
    max_cycles = len(pixels) * 5

    while len(outputs) < expected_count:
        cycle_count += 1
        assert cycle_count < max_cycles, (
            f"Timeout: received {len(outputs)} of {expected_count} FAST outputs"
        )
        await FallingEdge(dut.clk)

        # A real AXI source must hold valid/data until accepted.  New samples
        # occasionally arrive late to model upstream DMA gaps.
        if not holding and source_index < len(pixels):
            if rng.random() >= 0.12:
                x = source_index % WIDTH
                y = source_index // WIDTH
                dut.s_axis_tdata.value = int(pixels[source_index])
                dut.s_axis_tuser.value = int(source_index == 0)
                dut.s_axis_tlast.value = int(x == WIDTH - 1)
                dut.s_axis_tvalid.value = 1
                holding = True
            else:
                dut.s_axis_tvalid.value = 0
                dut.s_axis_tuser.value = 0
                dut.s_axis_tlast.value = 0
        elif not holding:
            dut.s_axis_tvalid.value = 0
            dut.s_axis_tuser.value = 0
            dut.s_axis_tlast.value = 0

        dut.m_ready.value = int(rng.random() >= 0.18)
        await Timer(1, unit="ns")

        source_fire = bool(
            int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value)
        )
        sink_valid = bool(int(dut.m_valid.value))
        sink_ready = bool(int(dut.m_ready.value))
        payload = None
        if sink_valid:
            payload = (
                int(dut.m_x.value),
                int(dut.m_y.value),
                int(dut.m_score.value),
                int(dut.m_corner.value),
                int(dut.m_sof.value),
                int(dut.m_eol.value),
            )

        if blocked_payload is not None:
            assert sink_valid, "m_valid dropped while output was blocked"
            assert payload == blocked_payload, "FAST output changed under backpressure"
        blocked_payload = payload if (sink_valid and not sink_ready) else None

        await RisingEdge(dut.clk)
        if source_fire:
            source_index += 1
            holding = False
        if sink_valid and sink_ready:
            outputs.append(payload)

    assert source_index == len(pixels), "Output completed before input frame ended"
    return outputs, cycle_count


@cocotb.test()
async def test_real_bookshelf_frame_matches_python_reference(dut):
    """Verify every interior score on a real image, including backpressure."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV and NumPy are required for this test") from exc

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    input_path = PANORAMA / "assets" / "input_720p" / "frame_001.jpg"
    source = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    assert source is not None, f"Cannot read {input_path}"
    gray = cv2.resize(source, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    reference = fast9_reference(gray)

    expected_count = (WIDTH - 6) * (HEIGHT - 6)
    outputs, cycles = await stream_frame_with_stalls(
        dut, gray, expected_count
    )

    rtl_score = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    previous = None
    for output_index, (x, y, score, corner, sof, eol) in enumerate(outputs):
        expected_x = 3 + (output_index % (WIDTH - 6))
        expected_y = 3 + (output_index // (WIDTH - 6))
        assert (x, y) == (expected_x, expected_y), (
            f"Raster coordinate mismatch at output {output_index}: "
            f"expected {(expected_x, expected_y)}, got {(x, y)}"
        )
        assert score == int(reference[y, x]), (
            f"FAST score mismatch at {(x, y)}: "
            f"expected {int(reference[y, x])}, got {score}"
        )
        assert corner == int(score > THRESHOLD)
        assert sof == int((x, y) == (3, 3))
        assert eol == int(x == WIDTH - 4)
        if previous is not None:
            assert (y > previous[1]) or (y == previous[1] and x == previous[0] + 1)
        previous = (x, y)
        rtl_score[y, x] = score

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    score_path = ARTIFACTS / "fast9_score_map.png"
    overlay_path = ARTIFACTS / "fast9_corner_overlay.jpg"
    assert cv2.imwrite(str(score_path), rtl_score)

    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    corner_y, corner_x = np.nonzero(rtl_score > THRESHOLD)
    for x, y in zip(corner_x.tolist(), corner_y.tolist()):
        cv2.circle(overlay, (x, y), 1, (0, 0, 255), 1)
    assert cv2.imwrite(str(overlay_path), overlay)

    report = {
        "status": "pass",
        "module": "orb_fast9_stream",
        "input": str(input_path),
        "simulation_resolution": [WIDTH, HEIGHT],
        "threshold": THRESHOLD,
        "interior_pixels_checked": expected_count,
        "corners_before_nms": int(np.count_nonzero(rtl_score > THRESHOLD)),
        "source_and_sink_stalls": True,
        "simulation_cycles": cycles,
        "score_mismatches": 0,
        "next_stage": "3x3 non-maximum suppression",
    }
    (ARTIFACTS / "fast9_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dut._log.info(
        "FAST-9 checked %d scores, found %d pre-NMS corners; artifacts: %s",
        expected_count,
        report["corners_before_nms"],
        ARTIFACTS,
    )
