#!/usr/bin/env python3
"""Record all four loader dependency trees, apt OpenCV presence and cooling sensors."""
import csv
import argparse
import json
import os
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', default=str(ROOT / 'reports/a2/preflight'))
args = parser.parse_args()
OUT = pathlib.Path(args.output)
OUT.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env["LD_LIBRARY_PATH"] = str(ROOT / "install/lib") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
version = subprocess.check_output([str(ROOT / "install/bin/opencv_version")], env=env, text=True).strip()
rows = []
for relative in ("Examples/Monocular/mono_euroc", "lib/libORB_SLAM3.so",
                 "Thirdparty/DBoW2/lib/libDBoW2.so", "Thirdparty/g2o/lib/libg2o.so"):
    artifact = ROOT / "vendor/ORB_SLAM3" / relative
    result = subprocess.run(["ldd", str(artifact)], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUT / (artifact.name + ".ldd.txt")).write_text(result.stdout)
    libraries = [line.strip() for line in result.stdout.splitlines() if "libopencv_" in line]
    good = result.returncode == 0 and "not found" not in result.stdout and version == "4.5.5"
    for library in libraries:
        match = re.search(r"=> (\S+)", library)
        good = good and match is not None and pathlib.Path(match.group(1)).resolve().parent == (ROOT / "install/lib").resolve()
        good = good and ".so.405" in library and ".so.4.2" not in library and ".so.402" not in library
    rows.append([relative, "PASS" if good else "FAIL", version, len(libraries), "; ".join(libraries)])
with (OUT / "linkage.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["artifact", "status", "installed_opencv_version", "opencv_dependencies", "resolved_libraries"])
    writer.writerows(rows)
packages = subprocess.run(["dpkg-query", "-W", "-f=${Package},${Version},${db:Status-Status}\n", "*opencv*"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
installed = [row for row in csv.reader(packages.stdout.splitlines()) if len(row) == 3 and row[2] == "installed"]
with (OUT / "apt_opencv.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["package", "version", "status"])
    writer.writerows(installed)
old_development = [row for row in installed if row[0].endswith("-dev") and row[1].startswith("4.2")]
cooling = []
for base in sorted(pathlib.Path("/sys/class/hwmon").glob("hwmon*")):
    for field in ("name", "pwm1", "pwm1_enable", "fan1_input"):
        path = base / field
        if path.exists():
            cooling.append([str(path), path.read_text().strip()])
for zone in sorted(pathlib.Path("/sys/class/thermal").glob("thermal_zone*")):
    cooling.append([str(zone / "type"), (zone / "type").read_text().strip()])
    cooling.append([str(zone / "temp"), (zone / "temp").read_text().strip()])
with (OUT / "cooling.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["sensor", "value"])
    writer.writerows(cooling)
decision = {"linkage_pass": all(row[1] == "PASS" for row in rows),
            "apt_opencv_installed": installed, "apt_42_development": old_development,
            "uninstall_requires_user_decision": bool(old_development)}
(OUT / "decision.json").write_text(json.dumps(decision, indent=2))
print("LINKAGE", "PASS" if decision["linkage_pass"] else "FAIL")
print("APT_OPENCV_INSTALLED", len(installed))
print("APT_42_DEVELOPMENT", len(old_development))
for row in old_development:
    print("DEVELOPMENT_PACKAGE", row[0], row[1])
print("COOLING: controller data saved; physical fan confirmation required")
if not decision["linkage_pass"]:
    raise SystemExit(1)
