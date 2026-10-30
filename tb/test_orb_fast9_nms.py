"""Cocotb verification for deterministic 3x3 FAST score suppression."""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

from test_orb_fast9_stream import fast9_reference


ROOT = Path(__file__).resolve().parents[1]
PANORAMA = ROOT / "panorama"
ARTIFACTS = PANORAMA / "build" / "rtl_orb"
WIDTH = 160
HEIGHT = 96
THRESHOLD = 20


def nms_reference(score):
    """Match the RTL's deterministic earlier/later-neighbour tie break."""
    import numpy as np

    keep = np.zeros(score.shape, dtype=np.uint8)
    for y in range(4, score.shape[0] - 4):
        for x in range(4, score.shape[1] - 4):
            center = int(score[y, x])
            earlier = (
                int(score[y - 1, x - 1]), int(score[y - 1, x]),
                int(score[y - 1, x + 1]), int(score[y, x - 1]),
            )
            later = (
                int(score[y, x + 1]), int(score[y + 1, x - 1]),
                int(score[y + 1, x]), int(score[y + 1, x + 1]),
            )
            keep[y, x] = int(
                center > THRESHOLD
                and center > max(earlier)
                and center >= max(later)
            )
    return keep


async def reset_dut(dut):
    dut.rst.value = 1
    dut.s_x.value = 0
    dut.s_y.value = 0
    dut.s_score.value = 0
    dut.s_corner.value = 0
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def stream_scores(dut, score, expected_count, seed=314159):
    inputs = [
        (x, y, int(score[y, x]))
        for y in range(3, HEIGHT - 3)
        for x in range(3, WIDTH - 3)
    ]
    rng = random.Random(seed)
    source_index = 0
    holding = False
    outputs = []
    blocked_payload = None
    cycles = 0

    while len(outputs) < expected_count:
        cycles += 1
        assert cycles < len(inputs) * 5
        await FallingEdge(dut.clk)

        if not holding and source_index < len(inputs):
            if rng.random() >= 0.13:
                x, y, value = inputs[source_index]
                dut.s_x.value = x
                dut.s_y.value = y
                dut.s_score.value = value
                dut.s_corner.value = int(value > THRESHOLD)
                dut.s_valid.value = 1
                holding = True
            else:
                dut.s_valid.value = 0
        elif not holding:
            dut.s_valid.value = 0

        dut.m_ready.value = int(rng.random() >= 0.19)
        await Timer(1, unit="ns")
        source_fire = bool(int(dut.s_valid.value) and int(dut.s_ready.value))
        sink_valid = bool(int(dut.m_valid.value))
        sink_ready = bool(int(dut.m_ready.value))
        payload = None
        if sink_valid:
            payload = (
                int(dut.m_x.value), int(dut.m_y.value),
                int(dut.m_score.value), int(dut.m_keep.value),
                int(dut.m_sof.value), int(dut.m_eol.value),
            )
        if blocked_payload is not None:
            assert sink_valid
            assert payload == blocked_payload, "NMS output changed under backpressure"
        blocked_payload = payload if (sink_valid and not sink_ready) else None

        await RisingEdge(dut.clk)
        if source_fire:
            source_index += 1
            holding = False
        if sink_valid and sink_ready:
            outputs.append(payload)

    assert source_index == len(inputs)
    return outputs, cycles


@cocotb.test()
async def test_nms_matches_real_image_score_map(dut):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV and NumPy are required for this test") from exc

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    input_path = PANORAMA / "assets" / "input_720p" / "frame_001.jpg"
    image = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    gray = cv2.resize(image, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    score = fast9_reference(gray)
    expected_keep = nms_reference(score)

    expected_count = (WIDTH - 8) * (HEIGHT - 8)
    outputs, cycles = await stream_scores(dut, score, expected_count)
    actual_keep = np.zeros(score.shape, dtype=np.uint8)

    for index, (x, y, value, keep, sof, eol) in enumerate(outputs):
        expected_x = 4 + (index % (WIDTH - 8))
        expected_y = 4 + (index // (WIDTH - 8))
        assert (x, y) == (expected_x, expected_y)
        assert value == int(score[y, x])
        assert keep == int(expected_keep[y, x])
        assert sof == int((x, y) == (4, 4))
        assert eol == int(x == WIDTH - 5)
        actual_keep[y, x] = keep

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    ys, xs = np.nonzero(actual_keep)
    for x, y in zip(xs.tolist(), ys.tolist()):
        cv2.circle(overlay, (x, y), 2, (0, 0, 255), 1)
    overlay_path = ARTIFACTS / "fast9_nms_overlay.jpg"
    assert cv2.imwrite(str(overlay_path), overlay)

    report = {
        "status": "pass",
        "module": "orb_fast9_nms",
        "simulation_resolution": [WIDTH, HEIGHT],
        "dense_scores_checked": expected_count,
        "pre_nms_corners": int(np.count_nonzero(score > THRESHOLD)),
        "post_nms_keypoints": int(np.count_nonzero(actual_keep)),
        "nms_mismatches": 0,
        "source_and_sink_stalls": True,
        "simulation_cycles": cycles,
        "tie_break": "strict against earlier raster neighbours, >= later neighbours",
    }
    (ARTIFACTS / "fast9_nms_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dut._log.info(
        "NMS checked %d scores and retained %d keypoints; overlay: %s",
        expected_count,
        report["post_nms_keypoints"],
        overlay_path,
    )
