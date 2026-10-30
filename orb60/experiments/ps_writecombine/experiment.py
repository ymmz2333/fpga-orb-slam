"""Run a bounded original-UIO versus WC experiment and restore the original driver."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import statistics
import subprocess
import sys
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--reuse-nc", action="store_true",
                        help="Reuse this run's completed original mapping gate after a preflight-only failure")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    root = source.parents[1]
    output = args.output.resolve()
    config = args.config or root / "build/local/board_router_ssh.json"
    ssh = [sys.executable, str(root / "scripts/board_ssh.py"), "--config", str(config)]
    module = output / "module/orb60_wc_uio.ko"
    if not module.is_file():
        raise RuntimeError("Build the module against the matching factory kernel first")
    provenance = json.loads((output / "kernel_provenance.json").read_text())
    assert provenance["live_config_exact"]
    expected = "4.14.0-xilinx SMP preempt mod_unload modversions ARMv7 p2v8"
    actual = subprocess.check_output(["modinfo", "-F", "vermagic", str(module)], text=True).strip()
    if actual != expected:
        raise RuntimeError("Module vermagic mismatch: " + actual)
    if ((output / "network_nc").exists() and not args.reuse_nc) or (output / "network_wc").exists():
        raise RuntimeError("Refusing to overwrite a previous A/B run")

    def run(command, logfile):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (output / logfile).write_text(result.stdout)
        if result.returncode:
            print(result.stdout[-6000:], flush=True)
            raise RuntimeError("%s failed with exit code %s; see the saved log" % (logfile, result.returncode))
        return result.stdout

    def remote(script, logfile):
        command = "sh -c " + shlex.quote((source / script).read_text())
        return run(ssh + ["--timeout", "45", command], logfile)

    def get(remote_path, local_path):
        run(ssh + ["--get", remote_path, str(output / local_path)], local_path + ".transfer.log")

    vectors = output / "vectors"
    vectors.mkdir(exist_ok=True)
    with tarfile.open(root / "build/linux/rk_router_20261021/deploy.tar.gz", "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.parts[0] not in ("test_images", "test_descriptors"):
                continue
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("Unsafe vector archive member")
            target = vectors / str(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    host = json.loads(config.read_text(encoding="utf-8-sig"))["host"]
    vector_args = ["--host", host, "--images", str(vectors / "test_images"),
                   "--descriptors", str(vectors / "test_descriptors")]
    if args.reuse_nc:
        prior = json.loads((output / "network_nc/result.json").read_text())
        assert prior["status"] == "PASS" and prior["all_records_exact"]
        assert prior["frames"] == args.frames and prior["window"] == 3
        assert (output / "board_nc.log").is_file()
        failures = output / "failed_attempts"
        failures.mkdir(exist_ok=True)
        prior_attempts = len(list(failures.glob("*.log")))
        (failures / ("activate_%02d.log" % prior_attempts)).write_text((output / "activate.log").read_text())
    else:
        run([sys.executable, str(root / "linux/benchmark_pipeline.py")] + vector_args +
            ["--frames", str(args.frames), "--window", "3", "--output", str(output / "network_nc")],
            "network_nc.log")
        get("/tmp/orb60-pipeline-wc-restored.log", "board_nc.log")
    print("ORIGINAL_UIO_NETWORK_EXACT_PASS", flush=True)
    for local, remote_name in ((source / "restore_board.sh", "/tmp/orb60-wc-restore.sh"),
                               (output / "ddr-bench-arm", "/tmp/orb60-wc-ddr-bench-arm"),
                               (module, "/tmp/orb60-wc-uio.ko")):
        run(ssh + ["--put", str(local), remote_name], local.name + ".upload.log")
    activated = False
    try:
        # Restore is attempted even if activation fails after changing a binding.
        activated = True
        text = remote("activate_board.sh", "activate.log")
        assert "WC_EXPERIMENT_ACTIVE" in text
        micro = [json.loads(line) for line in text.splitlines() if line.startswith('{"test":')]
        assert len(micro) == 2 and all(m["exact"] and m["scratch_restored"] and m["complete"] for m in micro)
        (output / "micro_wc.json").write_text(json.dumps(micro, indent=2) + "\n")
        print("WC_MAPPING_AND_COPY_EXACT_PASS", flush=True)
        run([sys.executable, str(root / "linux/test_board.py")] + vector_args +
            ["--repeat", "3", "--output", str(output / "exact_wc")], "exact_wc.log")
        run([sys.executable, str(root / "linux/benchmark_pipeline.py")] + vector_args +
            ["--frames", str(args.frames), "--window", "3", "--output", str(output / "network_wc")],
            "network_wc.log")
        print("WC_NETWORK_FULL_RECORD_EXACT_PASS", flush=True)
    finally:
        if activated:
            restored = remote("restore_board.sh", "restore.log")
            assert any(marker in restored for marker in ("WC_ORIGINAL_DRIVER_AND_SERVER_RESTORED",
                                                         "WC_ALREADY_RESTORED", "WC_NOT_ACTIVE"))
            print("ORIGINAL_DRIVER_AND_SERVER_RESTORED", flush=True)
    get("/tmp/orb60-wc-pipeline.log", "board_wc.log")
    nc = json.loads((output / "network_nc/result.json").read_text())
    wc = json.loads((output / "network_wc/result.json").read_text())
    stages = {}
    for label in ("nc", "wc"):
        rows = [json.loads(line.split(" ", 1)[1]) for line in
                (output / ("board_" + label + ".log")).read_text().splitlines()
                if line.startswith("PIPELINE_FRAME ")][-args.frames:]
        assert len(rows) == args.frames and [r["id"] for r in rows] == list(range(1, args.frames + 1))
        stages[label] = {key.replace("_ns", "_mean_ms"): statistics.mean(r[key] for r in rows) / 1e6
                         for key in ("rx_ns", "copy_ns", "input_crc_ns", "pl_ns", "snapshot_ns", "send_ns")}
    result = dict(status="PASS", scope="physical changing-input network A/B; not full SLAM", frames=args.frames,
                  original_uio_fps=nc["fps"], writecombine_fps=wc["fps"],
                  throughput_speedup=wc["fps"] / nc["fps"], all_records_exact=True,
                  stages=stages, micro_wc=micro, original_driver_restored=True,
                  server_sha256=hashlib.sha256((root / "build/linux/frame_pipeline_20261021/orb60-server-arm").read_bytes()).hexdigest(),
                  module_sha256=hashlib.sha256(module.read_bytes()).hexdigest())
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
