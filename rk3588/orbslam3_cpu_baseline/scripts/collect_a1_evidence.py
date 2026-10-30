#!/usr/bin/env python3
"""Collect final A1 acceptance facts and normalized synthetic timing CSVs."""
import csv
import hashlib
import os
import pathlib
import shutil
import subprocess

root = pathlib.Path(__file__).resolve().parent.parent
out = root / "reports/a1"
out.mkdir(parents=True, exist_ok=True)
checks = []
runtime_env = os.environ.copy()
runtime_env["LD_LIBRARY_PATH"] = str(root / "install/lib") + ":" + runtime_env.get("LD_LIBRARY_PATH", "")
(out / "runtime_environment.txt").write_text("LD_LIBRARY_PATH=" + runtime_env["LD_LIBRARY_PATH"] + "\n")


def command(args):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=runtime_env)
    if result.returncode:
        raise RuntimeError("Command failed: " + repr(args) + "\n" + result.stdout[-2000:])
    return result.stdout


def check(name, passed, detail):
    checks.append((name, "PASS" if passed else "FAIL", detail))


for script in sorted((root / "scripts").glob("*.sh")):
    command(["bash", "-n", str(script)])
command(["python3", "-m", "compileall", "-q", str(root / "scripts")])
check("script_syntax", True, "bash -n and board Python compileall")
with (out / "reproducibility_files.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["path", "sha256"])
    for directory in ("scripts", "patches"):
        for file in sorted((root / directory).iterdir()):
            if file.is_file():
                writer.writerow([str(file.relative_to(root)), hashlib.sha256(file.read_bytes()).hexdigest()])

for relative in ("vendor/ORB_SLAM3/lib/libORB_SLAM3.so", "vendor/ORB_SLAM3/Examples/Monocular/mono_euroc"):
    artifact = root / relative
    present = artifact.is_file() and artifact.stat().st_size > 0
    check(relative + ":exists", present, str(artifact))
    if present:
        elf = command(["readelf", "-h", str(artifact)])
        linkage = command(["ldd", str(artifact)])
        check(relative + ":arch", "AArch64" in elf, "ELF AArch64")
        check(relative + ":linkage", "not found" not in linkage, "ldd has no missing dependencies")
        (out / (artifact.name + ".ldd.txt")).write_text(linkage)
        check(relative + ":sha256", True, hashlib.sha256(artifact.read_bytes()).hexdigest())
cache = (root / "vendor/ORB_SLAM3/build/CMakeCache.txt").read_text()
library_flags = (root / "vendor/ORB_SLAM3/build/CMakeFiles/ORB_SLAM3.dir/flags.make").read_text()
example_flags = (root / "vendor/ORB_SLAM3/build/CMakeFiles/mono_euroc.dir/flags.make").read_text()
check("REGISTER_TIMES_option", "ORB_SLAM3_REGISTER_TIMES:BOOL=ON" in cache, "CMake option ON")
check("REGISTER_TIMES_library_and_example", all("-DREGISTER_TIMES" in text for text in (library_flags, example_flags)), "PUBLIC compile definition in both targets")
check("CXX14", "-std=c++14" in library_flags and "-std=c++14" in example_flags, "library and mono_euroc")
check("march_native", "-march=native" in library_flags, "retained after ARM GCC acceptance probe")
(out / "compile_flags.txt").write_text("LIBRARY\n" + library_flags + "\nEXAMPLE\n" + example_flags)
pangolin_cache = (root / "build/Pangolin/CMakeCache.txt").read_text()
check("Pangolin_canonical_source", "CMAKE_HOME_DIRECTORY:INTERNAL=" + str(root / "vendor/Pangolin") in pangolin_cache, "reproducible source directory")
check("installed_OpenCV_version", command([str(root / "install/bin/opencv_version")]).strip() == "4.5.5", "installed executable under runtime environment")
with (root / "logs/a1-runtime-runs.csv").open() as stream:
    runs = list(csv.DictReader(stream))
check("five_runtime_runs", len(runs) == 20 and all(row["status"] == "PASS" and row["exit_code"] == "0" for row in runs), "four checks x five runs; synthetic only")
names = ["image_rect_ms", "image_resize_ms", "orb_extract_ms", "stereo_match_ms", "imu_preint_ms", "pose_pred_ms", "local_map_track_ms", "keyframe_decision_ms", "track_total_ms"]
for run in range(1, 6):
    smoke_record = next(row for row in runs if row["run"] == str(run) and row["check"] == "mono_euroc_synthetic")
    smoke_id = smoke_record.get("smoke_id", str(run))
    smoke = root / ("runtime/smoke_a1_" + smoke_id)
    target = out / ("smoke_run_%d" % run)
    target.mkdir(exist_ok=True)
    for file in smoke.glob("*.txt"):
        shutil.copy2(file, target / file.name)
    shutil.copy2(smoke / "verification.csv", target / "verification.csv")
    with (smoke / "TrackingTimeStats.txt").open() as stream:
        next(stream)
        rows = list(csv.reader(stream))
    with (target / "tracking_times.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frame_index"] + names)
        writer.writerows([index] + row for index, row in enumerate(rows))
    log = (root / ("logs/a1-smoke-" + smoke_id + "-driver.log")).read_text()
    check("smoke_run_%d:viewer_off" % run, "Viewer: disabled" in log, "DISPLAY unset and --no-viewer")
    check("smoke_run_%d:timing_rows" % run, len(rows) == 24, "24 synthetic input frames")
for name in ("environment.csv", "environment.log", "source_versions.csv", "a1-runtime-runs.csv", "orb_commits.csv", "opencv-runtime-probe.csv", "parser-compiler-probes.csv"):
    shutil.copy2(root / "logs" / name, out / name)
for name in ("environment-final.csv", "environment-final.log"):
    if (root / "logs" / name).exists():
        shutil.copy2(root / "logs" / name, out / name)
for category, names in (
    ("failures", ("orb-cxx11-failure.log", "opencv-version-gdb.log", "a1-smoke-gdb.log", "a1-smoke-initial-driver.log")),
    ("build_logs", ("opencv-final-version.log", "opencv-configure.log", "opencv-build.log", "pangolin-configure.log", "pangolin-build.log", "orb-configure.log", "orb-build.log")),
):
    directory = out / category
    directory.mkdir(exist_ok=True)
    for name in names:
        if (root / "logs" / name).exists():
            shutil.copy2(root / "logs" / name, directory / name)
with (out / "acceptance.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["check", "status", "detail"])
    writer.writerows(checks)
diff = command(["git", "-C", str(root / "vendor/ORB_SLAM3"), "diff", "--stat", "v1.0-release", "HEAD"])
(out / "diff_summary.txt").write_text(diff)
(out / "orb_source_diff.patch").write_text(command(["git", "-C", str(root / "vendor/ORB_SLAM3"), "diff", "v1.0-release", "HEAD"]))
(out / "orb_source_tree.txt").write_text(command(["git", "-C", str(root / "vendor/ORB_SLAM3"), "rev-parse", "HEAD^{tree}"]))
with (out / "source_trees.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["component", "tag", "upstream_commit", "upstream_tree", "verification"])
    for name, tag in (("ORB_SLAM3", "v1.0-release"), ("Pangolin", "v0.8"), ("opencv", "4.5.5")):
        source = root / "vendor" / name
        clean = not command(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"]).strip()
        check(name + ":tracked_source_clean", clean, "source modifications are committed")
        commit = command(["git", "-C", str(source), "rev-parse", tag + "^{commit}"]).strip()
        tree = command(["git", "-C", str(source), "rev-parse", tag + "^{tree}"]).strip()
        marker = root / "logs" / (name + "-source-tree-verified")
        verified = marker.exists()
        if name != "ORB_SLAM3":
            actual = command(["git", "-C", str(source), "write-tree"]).strip()
            verified = verified and actual == tree
        check(name + ":upstream_source", verified, tree)
        writer.writerow([name, tag, commit, tree, "PASS" if verified else "FAIL"])
# Rewrite acceptance after adding source checks.
with (out / "acceptance.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["check", "status", "detail"])
    writer.writerows(checks)
failed = [name for name, status, detail in checks if status != "PASS"]
if failed:
    raise RuntimeError("A1 acceptance failed: " + ", ".join(failed))
print("A1_ACCEPTANCE_PASS")
print(diff)
print("Evidence directory:", out)
