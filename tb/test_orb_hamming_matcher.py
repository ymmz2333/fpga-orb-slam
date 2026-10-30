"""cocotb verification for the pipelined ORB Hamming matcher."""
import json
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer


ROOT = Path(__file__).resolve().parents[1]
PANORAMA = ROOT / "panorama"
ARTIFACTS = PANORAMA / "build" / "rtl_hamming"


def hamming(left, right):
    return (left ^ right).bit_count()


def expected_two(query, candidates):
    ranked = sorted(
        (
            (hamming(query, descriptor), stream_position, index)
            for stream_position, (index, descriptor) in enumerate(candidates)
        ),
        key=lambda item: (item[0], item[1]),
    )
    return {
        "best_distance": ranked[0][0],
        "best_index": ranked[0][2],
        "second_distance": ranked[1][0],
        "second_index": ranked[1][2],
    }


async def reset_dut(dut):
    dut.rst.value = 1
    dut.q_desc.value = 0
    dut.q_valid.value = 0
    dut.s_desc.value = 0
    dut.s_index.value = 0
    dut.s_last.value = 0
    dut.s_valid.value = 0
    dut.m_match_ready.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)


async def wait_signal_high(signal, clock, limit=100):
    for _ in range(limit):
        if int(signal.value):
            return
        await RisingEdge(clock)
        await Timer(1, unit="ns")
    raise AssertionError("Timed out waiting for {}".format(signal._name))


async def run_scan(dut, query, candidates, seed=1):
    """Send one query and its candidate stream, including random input gaps."""
    if len(candidates) < 2:
        raise ValueError("At least two candidates are required")

    await wait_signal_high(dut.q_ready, dut.clk)
    dut.q_desc.value = query
    dut.q_valid.value = 1
    await RisingEdge(dut.clk)
    dut.q_valid.value = 0

    rng = random.Random(seed)
    for position, (index, descriptor) in enumerate(candidates):
        # Gaps model a DDR/DMA source that cannot always supply data.
        if rng.random() < 0.20:
            dut.s_valid.value = 0
            await RisingEdge(dut.clk)

        await wait_signal_high(dut.s_ready, dut.clk)
        dut.s_desc.value = descriptor
        dut.s_index.value = index
        dut.s_last.value = int(position == len(candidates) - 1)
        dut.s_valid.value = 1
        await RisingEdge(dut.clk)
        dut.s_valid.value = 0
        dut.s_last.value = 0

    # Deliberately keep the result blocked, then verify that every result field
    # remains stable until ready is asserted.
    await wait_signal_high(dut.m_match_valid, dut.clk, limit=100)
    await Timer(1, unit="ns")
    result = {
        "best_index": int(dut.m_best_index.value),
        "best_distance": int(dut.m_best_distance.value),
        "second_index": int(dut.m_second_index.value),
        "second_distance": int(dut.m_second_distance.value),
    }
    for _ in range(3):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        held = {
            "best_index": int(dut.m_best_index.value),
            "best_distance": int(dut.m_best_distance.value),
            "second_index": int(dut.m_second_index.value),
            "second_distance": int(dut.m_second_distance.value),
        }
        assert int(dut.m_match_valid.value) == 1
        assert held == result, "Result changed while downstream was stalled"

    dut.m_match_ready.value = 1
    await RisingEdge(dut.clk)
    dut.m_match_ready.value = 0
    await Timer(1, unit="ns")
    return result


@cocotb.test()
async def test_directed_all_bits_and_result_backpressure(dut):
    """A bit-255 edge case catches the intentional off-by-one mutant."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    query = 0
    candidates = [
        (3, 1 << 255),        # distance 1; mutant incorrectly reports 0
        (7, 0),               # true best, distance 0
        (9, (1 << 256) - 1),  # distance 256
    ]
    actual = await run_scan(dut, query, candidates, seed=101)
    expected = expected_two(query, candidates)
    assert actual == expected, (
        "Hamming edge mismatch: expected {}, got {}. "
        "Check XOR bit coverage and the popcount tree.".format(expected, actual)
    )


@cocotb.test()
async def test_real_orb_descriptors_from_bookshelf_images(dut):
    """Compare RTL against exhaustive Python distances on real ORB data."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV and NumPy are required for the ORB test") from exc

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    dut._log.info("Embedded Python runtime: %s", sys.version.split()[0])

    first_path = PANORAMA / "assets" / "input_720p" / "frame_001.jpg"
    second_path = PANORAMA / "assets" / "input_720p" / "frame_002.jpg"
    first = cv2.imread(str(first_path), cv2.IMREAD_COLOR)
    second = cv2.imread(str(second_path), cv2.IMREAD_COLOR)
    assert first is not None and second is not None
    assert first.shape[:2] == (720, 1280)
    assert second.shape[:2] == (720, 1280)

    orb = cv2.ORB_create(nfeatures=600, fastThreshold=12)
    keypoints_a, descriptors_a = orb.detectAndCompute(
        cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), None
    )
    keypoints_b, descriptors_b = orb.detectAndCompute(
        cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), None
    )
    assert descriptors_a is not None and descriptors_b is not None
    assert descriptors_a.shape[1] == descriptors_b.shape[1] == 32

    candidate_count = min(320, len(descriptors_b))
    candidate_rows = descriptors_b[:candidate_count]
    candidate_ints = [
        int.from_bytes(row.tobytes(), byteorder="little")
        for row in candidate_rows
    ]
    candidates = list(enumerate(candidate_ints))

    # Select good real correspondences for a compact wave while still forcing
    # RTL to exhaustively compare each query with all 320 candidates.
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    software_knn = matcher.knnMatch(descriptors_a, candidate_rows, k=2)
    ranked_queries = sorted(
        (
            (pair[0].distance, query_index)
            for query_index, pair in enumerate(software_knn)
            if len(pair) == 2
        ),
        key=lambda item: item[0],
    )[:12]
    assert len(ranked_queries) == 12

    report_matches = []
    draw_matches = []
    for sequence, (_, query_index) in enumerate(ranked_queries):
        query = int.from_bytes(
            descriptors_a[query_index].tobytes(), byteorder="little"
        )
        expected = expected_two(query, candidates)
        actual = await run_scan(
            dut, query, candidates, seed=1000 + sequence
        )
        assert actual == expected, (
            "Real ORB mismatch for query {}: expected {}, got {}"
            .format(query_index, expected, actual)
        )
        ratio = actual["best_distance"] / max(1, actual["second_distance"])
        report_matches.append({
            "query_index": query_index,
            **actual,
            "ratio": round(ratio, 6),
        })
        draw_matches.append(cv2.DMatch(
            _queryIdx=query_index,
            _trainIdx=actual["best_index"],
            _distance=float(actual["best_distance"]),
        ))

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    visualization = cv2.drawMatches(
        first,
        keypoints_a,
        second,
        keypoints_b,
        draw_matches,
        None,
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    output_image = ARTIFACTS / "rtl_verified_matches.jpg"
    assert cv2.imwrite(str(output_image), visualization)

    report = {
        "status": "pass",
        "meaning": (
            "OpenCV generated the ORB descriptors; Verilog exhaustively "
            "computed the best and second-best Hamming matches."
        ),
        "input_resolution": [1280, 720],
        "query_descriptor_count": int(len(descriptors_a)),
        "candidate_descriptor_count_available": int(len(descriptors_b)),
        "candidate_descriptor_count_scanned_per_query": candidate_count,
        "queries_verified": len(report_matches),
        "rtl_candidates_checked": candidate_count * len(report_matches),
        "pipeline_accept_rate": "1 candidate/clock after fill",
        "matches": report_matches,
    }
    (ARTIFACTS / "rtl_hamming_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dut._log.info(
        "RTL verified %d Hamming comparisons; visualization: %s",
        report["rtl_candidates_checked"],
        output_image,
    )
