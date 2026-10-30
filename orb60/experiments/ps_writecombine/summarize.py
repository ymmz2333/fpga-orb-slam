"""Validate and summarize the WC trial, keeping WSL and RK measurements separate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics


def load(path):
    return json.loads(path.read_text())


def frames(path):
    return [json.loads(line.split(" ", 1)[1]) for line in path.read_text().splitlines()
            if line.startswith("PIPELINE_FRAME ")]


def profile(rows, count):
    assert len(rows) == count and [r["id"] for r in rows] == list(range(1, count + 1))
    return {key.replace("_ns", "_mean_ms"): statistics.mean(r[key] for r in rows) / 1e6
            for key in ("rx_ns", "copy_ns", "input_crc_ns", "pl_ns", "snapshot_ns",
                        "reply_crc_ns", "send_ns", "total_ns")}


def fingerprints(path):
    return re.findall(r"FPGA_ORB_NET frame=(\d+) .*?count=(\d+) .*?record_crc=(\d+)", path.read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    output = args.output.resolve()
    root = Path(__file__).resolve().parents[2]
    nc = load(output / "rk/network_nc/result.json")
    wc = load(output / "rk/network_wc/result.json")
    for result in (nc, wc):
        assert result["status"] == "PASS" and result["all_records_exact"] and result["frames"] == 180
    prior = root / "build/linux/frame_pipeline_20261021/slam_pipeline2273"
    current = output / "rk/slam_pipeline2273"
    old = load(prior / "status.json")
    new = load(current / "status.json")
    acceptance = load(output / "wc_full_acceptance.json")
    assert acceptance["status"] == "PASS"
    assert new["source_sha256"] == old["source_sha256"]
    assert new["executable_sha256"] == old["executable_sha256"]
    assert new["library_sha256"] == old["library_sha256"]
    old_crcs, new_crcs = fingerprints(prior / "output.log"), fingerprints(current / "output.log")
    assert len(old_crcs) == len(new_crcs) == 2273 and old_crcs == new_crcs
    nc_rows = frames(output / "board_rk_nc.log")[-180:]
    wc_rows = frames(output / "board_rk_wc.log")
    assert len(wc_rows) == 180 + 2273
    restore = (output / "restore_rk.log").read_text(encoding="utf-8-sig")
    assert "WC_ORIGINAL_DRIVER_AND_SERVER_RESTORED" in restore
    result = dict(status="PASS", implementation="PS Linux custom UIO DDR WC mapping; unchanged PL and server",
                  rk_changing180=dict(nc_fps=nc["fps"], wc_fps=wc["fps"],
                                      speedup=wc["fps"] / nc["fps"],
                                      exact=True, nc_profile=profile(nc_rows, 180),
                                      wc_profile=profile(wc_rows[:180], 180),
                                      nc_latency_ms=nc["latency_ms"], wc_latency_ms=wc["latency_ms"]),
                  slam2273=dict(previous_fps=old["processing_fps"], wc_fps=new["processing_fps"],
                                previous_seconds=old["processing_seconds"], wc_seconds=new["processing_seconds"],
                                historical_speedup=new["processing_fps"] / old["processing_fps"],
                                comparison="retained earlier run with identical source, binary, calibration and inputs",
                                all2273_record_crc_equal=True, profile=profile(wc_rows[180:], 2273),
                                acceptance=acceptance),
                  original_driver_and_server_restored=True,
                  source_sha256={f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                                 for f in Path(__file__).resolve().parent.iterdir() if f.is_file()},
                  module_sha256=hashlib.sha256((output / "module/orb60_wc_uio.ko").read_bytes()).hexdigest())
    (output / "rk_summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("source_sha256", "slam2273")}, indent=2))
    print("SLAM2273_WC", new["processing_fps"], "ALL2273_RECORD_CRC_EQUAL", "ORIGINAL_DRIVER_RESTORED")


if __name__ == "__main__":
    main()
